import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime
from typing import List, Dict, Tuple
import re

# Configuration - Try multiple possible locations
POSSIBLE_DIRS = [
    r"C:\Users\User\Downloads\Arbitrage Website\output",
    "output",
    "./output",
    "../output",
    os.path.join(os.getcwd(), "output"),
]

def find_output_dir():
    """Find the first valid output directory."""
    for directory in POSSIBLE_DIRS:
        if os.path.exists(directory):
            return directory
    return POSSIBLE_DIRS[0]  # Default to first option

OUT_DIR = find_output_dir()

# File paths for all three sites
FILES = {
    "SuperSportBET": {
        "csv": os.path.join(OUT_DIR, "supersport_premier.csv"),
        "json": os.path.join(OUT_DIR, "supersport_premier.json")
    },
    "SunBet": {
        "csv": os.path.join(OUT_DIR, "sunbet_premier.csv"),
        "json": os.path.join(OUT_DIR, "sunbet_premier.json")
    },
    "Betjets": {
        "csv": os.path.join(OUT_DIR, "betjets_epl.csv"),
        "json": os.path.join(OUT_DIR, "betjets_epl.json")
    }
}

def normalize_team_name(team: str) -> str:
    """Normalize team names for matching across different sites."""
    team = team.lower().strip()
    # Common abbreviations and variations
    replacements = {
        'man united': 'manchester united',
        'man utd': 'manchester united',
        'man city': 'manchester city',
        'spurs': 'tottenham',
        'tottenham hotspur': 'tottenham',
        'newcastle united': 'newcastle',
        'wolves': 'wolverhampton',
        'brighton & hove albion': 'brighton',
        'brighton and hove albion': 'brighton',
        'nottingham forest': 'nott\'m forest',
        'west ham united': 'west ham',
        'leicester city': 'leicester',
    }
    for old, new in replacements.items():
        if old in team:
            team = team.replace(old, new)
    return team

def load_data() -> pd.DataFrame:
    """Load and combine data from all three sites."""
    dfs = []
    found_files = []
    missing_files = []
    
    for site, paths in FILES.items():
        if os.path.exists(paths["csv"]):
            try:
                df = pd.read_csv(paths["csv"])
                if not df.empty:
                    df['normalized_home'] = df['home_team'].apply(normalize_team_name)
                    df['normalized_away'] = df['away_team'].apply(normalize_team_name)
                    dfs.append(df)
                    found_files.append(f"{site}: {len(df)} matches")
                else:
                    missing_files.append(f"{site}: File exists but empty")
            except Exception as e:
                missing_files.append(f"{site}: Error - {e}")
        else:
            missing_files.append(f"{site}: File not found at {paths['csv']}")
    
    # Show status in sidebar
    if found_files:
        st.sidebar.success(f"✅ Loaded {len(found_files)} source(s)")
        for f in found_files:
            st.sidebar.text(f)
    if missing_files:
        st.sidebar.warning(f"⚠️ Missing {len(missing_files)} source(s)")
        for f in missing_files:
            st.sidebar.text(f)
    
    if dfs:
        return pd.concat(dfs, ignore_index=True)
    return pd.DataFrame()

def calculate_arbitrage(odds_home: float, odds_draw: float, odds_away: float) -> Tuple[float, bool]:
    """Calculate if arbitrage exists and the profit margin."""
    try:
        implied_prob = (1/odds_home + 1/odds_draw + 1/odds_away)
        profit_margin = (1/implied_prob - 1) * 100
        is_arb = implied_prob < 1.0
        return profit_margin, is_arb
    except (ZeroDivisionError, TypeError):
        return 0.0, False

def find_arbitrage_opportunities(df: pd.DataFrame) -> List[Dict]:
    """Find arbitrage opportunities across different bookmakers."""
    opportunities = []
    
    # Group by match (normalized team names and date)
    matches = df.groupby(['normalized_home', 'normalized_away', 'date'])
    
    for (home, away, date), group in matches:
        if len(group) < 2:  # Need at least 2 bookmakers
            continue
        
        # Get best odds for each outcome across all bookmakers
        best_home = group.loc[group['odds_home'].idxmax()]
        best_draw = group.loc[group['odds_draw'].idxmax()]
        best_away = group.loc[group['odds_away'].idxmax()]
        
        # Calculate arbitrage
        profit_margin, is_arb = calculate_arbitrage(
            best_home['odds_home'],
            best_draw['odds_draw'],
            best_away['odds_away']
        )
        
        if is_arb:
            # Calculate stake distribution for 100 total stake
            total_stake = 100
            stake_home = total_stake / (best_home['odds_home'] * (1/best_home['odds_home'] + 1/best_draw['odds_draw'] + 1/best_away['odds_away']))
            stake_draw = total_stake / (best_draw['odds_draw'] * (1/best_home['odds_home'] + 1/best_draw['odds_draw'] + 1/best_away['odds_away']))
            stake_away = total_stake / (best_away['odds_away'] * (1/best_home['odds_home'] + 1/best_draw['odds_draw'] + 1/best_away['odds_away']))
            
            guaranteed_return = stake_home * best_home['odds_home']
            profit = guaranteed_return - total_stake
            
            opportunities.append({
                'home_team': best_home['home_team'],
                'away_team': best_away['away_team'],
                'date': date,
                'start_time': best_home['start_time'],
                'profit_margin': profit_margin,
                'profit_amount': profit,
                'best_home_odds': best_home['odds_home'],
                'best_home_source': best_home['source'],
                'stake_home': stake_home,
                'best_draw_odds': best_draw['odds_draw'],
                'best_draw_source': best_draw['source'],
                'stake_draw': stake_draw,
                'best_away_odds': best_away['odds_away'],
                'best_away_source': best_away['source'],
                'stake_away': stake_away,
                'total_stake': total_stake,
                'guaranteed_return': guaranteed_return
            })
    
    return sorted(opportunities, key=lambda x: x['profit_margin'], reverse=True)

def main():
    st.set_page_config(page_title="Arbitrage Betting Analyzer", layout="wide", page_icon="⚽")
    
    st.title("⚽ Premier League Arbitrage Betting Analyzer")
    st.markdown("---")
    
    # Show current output directory
    st.sidebar.info(f"📁 Output Directory:\n`{OUT_DIR}`")
    
    # Load data
    with st.spinner("Loading betting data..."):
        df = load_data()
    
    if df.empty:
        st.error("❌ No data found or all files are empty.")
        
        st.warning("**Checking file locations...**")
        
        # Show which files exist
        st.write("**File Status:**")
        for site, paths in FILES.items():
            exists = os.path.exists(paths["csv"])
            icon = "✅" if exists else "❌"
            st.write(f"{icon} {site}: `{paths['csv']}`")
            if exists:
                try:
                    test_df = pd.read_csv(paths["csv"])
                    st.write(f"   → Contains {len(test_df)} rows")
                except Exception as e:
                    st.write(f"   → Error reading: {e}")
        
        st.info("""
        **To fix this:**
        1. Make sure you've run the scraping scripts
        2. Check that CSV files exist in the output folder
        3. Verify the output path matches: `{}`
        
        **Or manually set the path:**
        Update `OUT_DIR` in the script to point to your output folder.
        """.format(OUT_DIR))
        return
    
    # Sidebar filters
    st.sidebar.header("Filters")
    
    sources = ['All'] + sorted(df['source'].unique().tolist())
    selected_source = st.sidebar.selectbox("Bookmaker", sources)
    
    dates = ['All'] + sorted(df['date'].unique().tolist())
    selected_date = st.sidebar.selectbox("Match Date", dates)
    
    # Filter data
    filtered_df = df.copy()
    if selected_source != 'All':
        filtered_df = filtered_df[filtered_df['source'] == selected_source]
    if selected_date != 'All':
        filtered_df = filtered_df[filtered_df['date'] == selected_date]
    
    # Tabs
    tab1, tab2, tab3 = st.tabs(["🎯 Arbitrage Opportunities", "📊 All Odds", "📈 Statistics"])
    
    with tab1:
        st.header("Arbitrage Opportunities")
        st.markdown("These are guaranteed profit opportunities by betting on all outcomes across different bookmakers.")
        
        opportunities = find_arbitrage_opportunities(df)
        
        if opportunities:
            st.success(f"Found {len(opportunities)} arbitrage opportunities!")
            
            for i, opp in enumerate(opportunities, 1):
                with st.expander(f"**Opportunity #{i}: {opp['home_team']} vs {opp['away_team']}** - Profit: {opp['profit_margin']:.2f}% (R{opp['profit_amount']:.2f})"):
                    col1, col2 = st.columns([1, 2])
                    
                    with col1:
                        st.markdown(f"**Match Details**")
                        st.write(f"📅 {opp['date']}")
                        st.write(f"⏰ {opp['start_time']}")
                        st.write(f"💰 Profit Margin: **{opp['profit_margin']:.2f}%**")
                        st.write(f"💵 Profit on R100: **R{opp['profit_amount']:.2f}**")
                    
                    with col2:
                        st.markdown("**Betting Strategy (for R100 total stake)**")
                        
                        # Create three columns for each bet
                        bet_col1, bet_col2, bet_col3 = st.columns(3)
                        
                        with bet_col1:
                            st.markdown(f"**🏠 Home Win**")
                            st.write(f"Team: {opp['home_team']}")
                            st.write(f"Bookmaker: {opp['best_home_source']}")
                            st.write(f"Odds: {opp['best_home_odds']}")
                            st.write(f"Stake: R{opp['stake_home']:.2f}")
                            st.write(f"Return: R{opp['guaranteed_return']:.2f}")
                        
                        with bet_col2:
                            st.markdown(f"**🤝 Draw**")
                            st.write(f"Bookmaker: {opp['best_draw_source']}")
                            st.write(f"Odds: {opp['best_draw_odds']}")
                            st.write(f"Stake: R{opp['stake_draw']:.2f}")
                            st.write(f"Return: R{opp['guaranteed_return']:.2f}")
                        
                        with bet_col3:
                            st.markdown(f"**✈️ Away Win**")
                            st.write(f"Team: {opp['away_team']}")
                            st.write(f"Bookmaker: {opp['best_away_source']}")
                            st.write(f"Odds: {opp['best_away_odds']}")
                            st.write(f"Stake: R{opp['stake_away']:.2f}")
                            st.write(f"Return: R{opp['guaranteed_return']:.2f}")
        else:
            st.info("No arbitrage opportunities found at the moment. Keep checking as odds change!")
            st.markdown("""
            **What is Arbitrage Betting?**
            
            Arbitrage betting (or "arbing") is when you bet on all possible outcomes of an event 
            across different bookmakers to guarantee a profit regardless of the result. This happens 
            when bookmakers have different opinions on the odds.
            
            **Example:** If one bookmaker offers high odds on Team A winning, and another offers 
            high odds on Team B winning, you might be able to bet on both and guarantee profit.
            """)
    
    with tab2:
        st.header("All Available Odds")
        
        # Display metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Matches", len(filtered_df))
        col2.metric("Bookmakers", filtered_df['source'].nunique())
        col3.metric("Dates Available", filtered_df['date'].nunique())
        col4.metric("Avg Home Odds", f"{filtered_df['odds_home'].mean():.2f}")
        
        st.markdown("---")
        
        # Display table
        display_df = filtered_df[['home_team', 'away_team', 'date', 'start_time', 
                                   'odds_home', 'odds_draw', 'odds_away', 'source']].copy()
        display_df.columns = ['Home Team', 'Away Team', 'Date', 'Time', 
                              'Home Odds', 'Draw Odds', 'Away Odds', 'Bookmaker']
        
        st.dataframe(display_df, use_container_width=True, height=400)
        
        # Download button
        csv = display_df.to_csv(index=False)
        st.download_button(
            label="📥 Download as CSV",
            data=csv,
            file_name=f"premier_league_odds_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    
    with tab3:
        st.header("Statistics & Insights")
        
        # Arbitrage Calculation Explanation Section
        st.subheader("📚 Understanding Arbitrage Betting")
        
        with st.expander("**How Arbitrage Works - Click to Learn**", expanded=False):
            st.markdown("""
            ### What is Arbitrage Betting?
            
            Arbitrage betting (also called "sure betting" or "arbing") is a strategy that guarantees profit by placing bets 
            on all possible outcomes of an event across different bookmakers. This works when bookmakers disagree on the 
            odds, creating a mathematical opportunity for guaranteed profit.
            
            ---
            
            ### The Mathematics Behind It
            
            #### 1. **Implied Probability**
            When a bookmaker offers odds, they're expressing the probability of an outcome. For example:
            - Odds of 2.00 = 50% implied probability (1 ÷ 2.00 = 0.50)
            - Odds of 3.00 = 33.33% implied probability (1 ÷ 3.00 = 0.333)
            
            #### 2. **The Arbitrage Formula**
            For a 3-way market (Home/Draw/Away), we calculate:
            
            ```
            Arbitrage % = (1/Odds_Home + 1/Odds_Draw + 1/Odds_Away) × 100
            ```
            
            - **If < 100%**: Arbitrage opportunity exists! ✅
            - **If = 100%**: Break-even (no profit, no loss)
            - **If > 100%**: Bookmaker has built-in margin (normal situation)
            
            #### 3. **Profit Margin Calculation**
            
            ```
            Profit Margin % = (1 / Arbitrage% - 1) × 100
            ```
            
            ---
            
            ### Example Calculation
            """)
            
            st.markdown("#### **Scenario: Manchester United vs Liverpool**")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.info("**Home Win (Man Utd)**\n\nBookmaker A: 2.10")
            with col2:
                st.info("**Draw**\n\nBookmaker B: 3.80")
            with col3:
                st.info("**Away Win (Liverpool)**\n\nBookmaker C: 4.20")
            
            # Calculate the example
            ex_home, ex_draw, ex_away = 2.10, 3.80, 4.20
            ex_arb = (1/ex_home + 1/ex_draw + 1/ex_away)
            ex_profit_margin = (1/ex_arb - 1) * 100
            
            st.markdown(f"""
            #### **Step-by-Step Calculation:**
            
            **Step 1:** Calculate implied probabilities
            ```
            Home: 1 ÷ 2.10 = 0.4762 (47.62%)
            Draw: 1 ÷ 3.80 = 0.2632 (26.32%)
            Away: 1 ÷ 4.20 = 0.2381 (23.81%)
            ```
            
            **Step 2:** Sum the implied probabilities
            ```
            Total = 0.4762 + 0.2632 + 0.2381 = 0.9775 (97.75%)
            ```
            
            **Step 3:** Check if arbitrage exists
            ```
            97.75% < 100% ✅ YES! Arbitrage opportunity exists!
            ```
            
            **Step 4:** Calculate profit margin
            ```
            Profit Margin = (1 ÷ 0.9775 - 1) × 100 = {ex_profit_margin:.2f}%
            ```
            
            ---
            
            ### How to Split Your Stakes
            
            For a **R1,000 total investment**, calculate each stake as:
            
            ```
            Stake_Outcome = Total_Investment ÷ (Odds_Outcome × Total_Implied_Probability)
            ```
            """)
            
            total_stake = 1000
            stake_home = total_stake / (ex_home * ex_arb)
            stake_draw = total_stake / (ex_draw * ex_arb)
            stake_away = total_stake / (ex_away * ex_arb)
            guaranteed_return = stake_home * ex_home
            profit = guaranteed_return - total_stake
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.success(f"""
                **Bet on Man Utd Win**
                - Stake: R{stake_home:.2f}
                - At odds: 2.10
                - Returns: R{stake_home * ex_home:.2f}
                """)
            with col2:
                st.success(f"""
                **Bet on Draw**
                - Stake: R{stake_draw:.2f}
                - At odds: 3.80
                - Returns: R{stake_draw * ex_draw:.2f}
                """)
            with col3:
                st.success(f"""
                **Bet on Liverpool Win**
                - Stake: R{stake_away:.2f}
                - At odds: 4.20
                - Returns: R{stake_away * ex_away:.2f}
                """)
            
            st.markdown(f"""
            ### **Final Result:**
            
            - **Total Staked:** R{total_stake:.2f}
            - **Guaranteed Return:** R{guaranteed_return:.2f} (regardless of match outcome)
            - **Guaranteed Profit:** R{profit:.2f}
            - **ROI:** {ex_profit_margin:.2f}%
            
            ---
            
            ### Why Does This Work?
            
            Different bookmakers:
            1. Have different opinions on match outcomes
            2. Target different customer segments
            3. Update their odds at different times
            4. Use different risk management strategies
            
            By finding the **best odds for each outcome across multiple bookmakers**, you can sometimes create a situation 
            where the combined implied probability is less than 100%, guaranteeing profit!
            
            ---
            
            ### Important Notes
            
            ⚠️ **Challenges in Real-World Arbitrage:**
            - Odds change rapidly - opportunities may disappear quickly
            - Bookmakers may limit or ban accounts that consistently arb
            - Need accounts with multiple bookmakers
            - Must place bets simultaneously to lock in odds
            - Betting limits may prevent large stakes
            - Account verification and withdrawal times vary
            
            ✅ **Best Practices:**
            - Act quickly when opportunities arise
            - Use reliable, licensed bookmakers
            - Keep accounts funded for fast execution
            - Calculate stakes accurately
            - Verify odds before placing bets
            - Track all bets carefully
            """)
        
        st.markdown("---")
        
        # Real Data Analysis Section
        st.subheader("🔍 Arbitrage Analysis of Your Data")
        
        with st.expander("**Analyze All Matches - Click to See Detailed Breakdown**", expanded=True):
            st.markdown("This section analyzes every match in your data to show whether arbitrage opportunities exist.")
            
            # Group matches and analyze each one
            matches = df.groupby(['normalized_home', 'normalized_away', 'date'])
            
            analysis_data = []
            
            for (home, away, date), group in matches:
                # Get best odds for each outcome
                best_home_row = group.loc[group['odds_home'].idxmax()]
                best_draw_row = group.loc[group['odds_draw'].idxmax()]
                best_away_row = group.loc[group['odds_away'].idxmax()]
                
                best_home_odds = best_home_row['odds_home']
                best_draw_odds = best_draw_row['odds_draw']
                best_away_odds = best_away_row['odds_away']
                
                # Calculate arbitrage
                implied_prob_home = 1 / best_home_odds
                implied_prob_draw = 1 / best_draw_odds
                implied_prob_away = 1 / best_away_odds
                total_implied_prob = implied_prob_home + implied_prob_draw + implied_prob_away
                
                arbitrage_pct = total_implied_prob * 100
                profit_margin = (1/total_implied_prob - 1) * 100 if total_implied_prob < 1 else 0
                is_arbitrage = total_implied_prob < 1.0
                
                analysis_data.append({
                    'match': f"{best_home_row['home_team']} vs {best_away_row['away_team']}",
                    'date': date,
                    'home_team': best_home_row['home_team'],
                    'away_team': best_away_row['away_team'],
                    'bookmakers': len(group),
                    'best_home_odds': best_home_odds,
                    'home_source': best_home_row['source'],
                    'best_draw_odds': best_draw_odds,
                    'draw_source': best_draw_row['source'],
                    'best_away_odds': best_away_odds,
                    'away_source': best_away_row['source'],
                    'implied_prob_home': implied_prob_home * 100,
                    'implied_prob_draw': implied_prob_draw * 100,
                    'implied_prob_away': implied_prob_away * 100,
                    'total_implied_prob': arbitrage_pct,
                    'profit_margin': profit_margin,
                    'is_arbitrage': is_arbitrage
                })
            
            # Sort by profit margin (arbitrage opportunities first)
            analysis_data.sort(key=lambda x: x['profit_margin'], reverse=True)
            
            # Summary statistics
            total_matches = len(analysis_data)
            arb_matches = sum(1 for a in analysis_data if a['is_arbitrage'])
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Unique Matches", total_matches)
            col2.metric("Arbitrage Opportunities", arb_matches, delta=f"{(arb_matches/total_matches*100):.1f}%" if total_matches > 0 else "0%")
            col3.metric("Regular Matches (No Arb)", total_matches - arb_matches)
            
            st.markdown("---")
            
            # Display each match analysis
            for i, analysis in enumerate(analysis_data, 1):
                if analysis['is_arbitrage']:
                    header_color = "🟢"
                    status = "ARBITRAGE OPPORTUNITY"
                else:
                    header_color = "🔴"
                    status = "NO ARBITRAGE"
                
                with st.expander(f"{header_color} **{analysis['match']}** ({analysis['date']}) - {status}"):
                    st.markdown(f"**Match has {analysis['bookmakers']} bookmaker(s) offering odds**")
                    
                    # Show best odds from each bookmaker
                    st.markdown("##### Best Odds Available:")
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.info(f"**🏠 {analysis['home_team']} Win**\n\n"
                               f"Best Odds: **{analysis['best_home_odds']}**\n\n"
                               f"Source: {analysis['home_source']}\n\n"
                               f"Implied Probability: {analysis['implied_prob_home']:.2f}%")
                    
                    with col2:
                        st.info(f"**🤝 Draw**\n\n"
                               f"Best Odds: **{analysis['best_draw_odds']}**\n\n"
                               f"Source: {analysis['draw_source']}\n\n"
                               f"Implied Probability: {analysis['implied_prob_draw']:.2f}%")
                    
                    with col3:
                        st.info(f"**✈️ {analysis['away_team']} Win**\n\n"
                               f"Best Odds: **{analysis['best_away_odds']}**\n\n"
                               f"Source: {analysis['away_source']}\n\n"
                               f"Implied Probability: {analysis['implied_prob_away']:.2f}%")
                    
                    st.markdown("---")
                    st.markdown("##### Arbitrage Calculation:")
                    
                    # Show the calculation
                    st.code(f"""
Step 1: Calculate Implied Probabilities
  Home: 1 ÷ {analysis['best_home_odds']} = {analysis['implied_prob_home']:.4f}% 
  Draw: 1 ÷ {analysis['best_draw_odds']} = {analysis['implied_prob_draw']:.4f}%
  Away: 1 ÷ {analysis['best_away_odds']} = {analysis['implied_prob_away']:.4f}%

Step 2: Sum Total Implied Probability
  Total = {analysis['implied_prob_home']:.2f}% + {analysis['implied_prob_draw']:.2f}% + {analysis['implied_prob_away']:.2f}%
  Total = {analysis['total_implied_prob']:.2f}%

Step 3: Check for Arbitrage
  {analysis['total_implied_prob']:.2f}% {'<' if analysis['is_arbitrage'] else '>'} 100%
  Result: {'✅ ARBITRAGE EXISTS!' if analysis['is_arbitrage'] else '❌ No arbitrage (bookmaker margin)'}
  
  {'Profit Margin: ' + f"{analysis['profit_margin']:.2f}%" if analysis['is_arbitrage'] else 'Bookmaker Margin: ' + f"{analysis['total_implied_prob'] - 100:.2f}%"}
                    """)
                    
                    if analysis['is_arbitrage']:
                        # Calculate stake distribution
                        total_stake = 1000
                        stake_home = total_stake / (analysis['best_home_odds'] * (analysis['total_implied_prob']/100))
                        stake_draw = total_stake / (analysis['best_draw_odds'] * (analysis['total_implied_prob']/100))
                        stake_away = total_stake / (analysis['best_away_odds'] * (analysis['total_implied_prob']/100))
                        guaranteed_return = stake_home * analysis['best_home_odds']
                        profit = guaranteed_return - total_stake
                        
                        st.success(f"""
**💰 Profit Opportunity:**

For a R1,000 total investment:
- Bet R{stake_home:.2f} on {analysis['home_team']} at {analysis['home_source']}
- Bet R{stake_draw:.2f} on Draw at {analysis['draw_source']}
- Bet R{stake_away:.2f} on {analysis['away_team']} at {analysis['away_source']}

**Guaranteed Return: R{guaranteed_return:.2f}**
**Guaranteed Profit: R{profit:.2f}**
**ROI: {analysis['profit_margin']:.2f}%**
                        """)
                    else:
                        st.warning(f"""
**Why No Arbitrage?**

The total implied probability ({analysis['total_implied_prob']:.2f}%) is greater than 100%, 
meaning the bookmakers have built in a {analysis['total_implied_prob'] - 100:.2f}% margin.

This is the normal situation - bookmakers price their odds to guarantee themselves profit.
To find arbitrage, we need the combined best odds to total less than 100%.
                        """)
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Odds by Bookmaker")
            avg_odds = df.groupby('source')[['odds_home', 'odds_draw', 'odds_away']].mean()
            st.dataframe(avg_odds.style.format("{:.2f}"), use_container_width=True)
            
            st.subheader("Matches by Bookmaker")
            match_counts = df.groupby('source').size().reset_index(name='count')
            st.bar_chart(match_counts.set_index('source'))
        
        with col2:
            st.subheader("Matches by Date")
            date_counts = df.groupby('date').size().reset_index(name='count')
            st.bar_chart(date_counts.set_index('date'))
            
            st.subheader("Best Odds Comparison")
            st.write("**Highest Home Odds:**")
            best_home = df.nlargest(3, 'odds_home')[['home_team', 'away_team', 'odds_home', 'source']]
            st.dataframe(best_home, use_container_width=True)
            
            st.write("**Highest Away Odds:**")
            best_away = df.nlargest(3, 'odds_away')[['home_team', 'away_team', 'odds_away', 'source']]
            st.dataframe(best_away, use_container_width=True)
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center'>
        <p>⚠️ <strong>Disclaimer:</strong> Gambling involves risk. Please bet responsibly. 
        This tool is for educational purposes only.</p>
        <p>Last updated: {}</p>
    </div>
    """.format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")), unsafe_allow_html=True)

if __name__ == "__main__":
    main()
