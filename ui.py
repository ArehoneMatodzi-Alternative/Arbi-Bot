import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime
from typing import List, Dict, Tuple
import re

# Configuration
OUT_DIR = r"C:\Users\User\Downloads\Arbitrage Website\output"

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
    
    for site, paths in FILES.items():
        if os.path.exists(paths["csv"]):
            try:
                df = pd.read_csv(paths["csv"])
                df['normalized_home'] = df['home_team'].apply(normalize_team_name)
                df['normalized_away'] = df['away_team'].apply(normalize_team_name)
                dfs.append(df)
            except Exception as e:
                st.warning(f"Error loading {site}: {e}")
    
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
    
    # Load data
    with st.spinner("Loading betting data..."):
        df = load_data()
    
    if df.empty:
        st.error("No data found. Please run the scraping scripts first.")
        st.info("""
        Run these scripts to collect data:
        1. `python supersport_scraper.py`
        2. `python sunbet_scraper.py`
        3. `python betjets_scraper.py`
        """)
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