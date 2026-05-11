import streamlit as st
import feedparser
import pandas as pd
from urllib.parse import quote
import ssl
from datetime import datetime
import concurrent.futures

# --- 1. DATA STRUCTURE ---
# NOTE 1: Replaced SUBS_MAP and CORE_TICKERS with the new coverage list from the image.
# Reference names with semicolons (like Dream Office and BSR) are split into multiple search terms.
COVERAGE = {
    "Allied Properties": {"ticker": "AP.UN", "full_name": "Allied Properties Real Estate Investment Trust", "ref_names": ["Allied Properties"]},
    "Automotive Properties": {"ticker": "APR.UN", "full_name": "Automotive Properties Real Estate Investment Trust", "ref_names": ["Automotive Properties Re"]},
    "Boardwalk": {"ticker": "BEI.UN", "full_name": "Boardwalk Real Estate Investment Trust", "ref_names": ["Boardwalk Re"]},
    "Canadian Apartment Properties": {"ticker": "CAR.UN", "full_name": "Canadian Apartment Properties Real Estate Investment Trust", "ref_names": ["Canadian Apartment Properties Re"]},
    "Chartwell": {"ticker": "CSH.UN", "full_name": "Chartwell Retirement Residences", "ref_names": ["Chartwell"]},
    "Dream Office": {"ticker": "D.UN", "full_name": "Dream Office Real Estate Investment Trust", "ref_names": ["Dream Office Real Estate Investment Trust", "Dream Office REIT"]},
    "BSR": {"ticker": "HOM-U", "full_name": "BSR Real Estate Investment Trust", "ref_names": ["BSR Real Estate Investment Trust", "BSR REIT"]},
    "Killam Apartment": {"ticker": "KMP.UN", "full_name": "Killam Apartment REIT", "ref_names": ["Killam Apartment Re"]},
    "Dream Impact": {"ticker": "MPCT.UN", "full_name": "Dream Impact Trust", "ref_names": ["Dream Impact Trust"]},
    "NexLiving": {"ticker": "NXLV", "full_name": "NexLiving Communities Inc.", "ref_names": ["NexLiving"]},
    "Parkit": {"ticker": "PKT", "full_name": "Parkit Enterprise Inc.", "ref_names": ["Parkit"]},
    "Pro REIT": {"ticker": "PRV.UN", "full_name": "Pro Real Estate Investment Trust", "ref_names": ["Pro Real Estate Investment Trust", "Pro REIT"]},
    "Slate Grocery": {"ticker": "SGR-U", "full_name": "Slate Grocery REIT", "ref_names": ["Slate Grocery"]},
    "Sienna Senior Living": {"ticker": "SIA", "full_name": "Sienna Senior Living Inc.", "ref_names": ["Sienna Senior Living"]},
    "StorageVault": {"ticker": "SVI", "full_name": "StorageVault Canada Inc.", "ref_names": ["StorageVault"]},
    "Vital Infrastructure": {"ticker": "VITL.UN", "full_name": "Vital Infrastructure Property Trust", "ref_names": ["Vital Infrastructure Property Trust"]},
    "Nexus Industrial": {"ticker": "NXR.UN", "full_name": "Nexus Industrial REIT", "ref_names": ["Nexus Industrial"]},
    "Dream Industrial": {"ticker": "DIR.UN", "full_name": "Dream Industrial Real Estate Investment Trust", "ref_names": ["Dream Industrial Re"]},
    "Granite REIT": {"ticker": "GRT.UN", "full_name": "Granite Real Estate Investment Trust", "ref_names": ["Granite Real Estate Investment Trust", "Granite REIT"]}
}

# --- 2. SOURCE CLASSIFICATION ---
# NOTE 2: Removed non-credible logic. We will strictly enforce that articles come from this list or the company itself.
CREDIBLE_KEYWORDS = [
    "Bloomberg", "Reuters", "Globe and Mail", "Financial Post", "CNBC", 
    "The Star", "BNN", "Wall Street Journal", "WSJ", "Barron's", "Financial Times", 
    "Associated Press", "AP", "Canadian Press", "GlobeNewswire", "Globe Newswire", 
    "CNW Group", "PR Newswire", "Business Wire", "BusinessWire", "Accesswire", 
    "Newsfile", "Marketwired", "Morningstar", "Barchart", "Seeking Alpha", 
    "MarketWatch", "Newswire", "TMX", "Press Release", "Government of Canada", 
]

def is_credible_source(source_name, company_name=""):
    """Returns True only if the source is credible or directly from the company."""
    if not source_name: return False
    source_lower = str(source_name).lower()
    
    # Check if the source is the company itself
    if company_name and company_name.lower() in source_lower:
        return True
    
    # Check official credible keywords
    if any(k.lower() in source_lower for k in CREDIBLE_KEYWORDS):
        return True
        
    return False

# --- 3. THE SCANNER ---
def get_google_news(search_term, display_name, validation_list):
    query = quote(f'{search_term} when:14d')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-CA&gl=CA&ceid=CA:en"
    
    if hasattr(ssl, '_create_unverified_context'):
        ssl._create_default_https_context = ssl._create_unverified_context
        
    feed = feedparser.parse(url)
    results = []
    
    for entry in feed.entries[:30]:
        headline = entry.title
        headline_lower = headline.lower()
        
        # HEADLINE VALIDATION: Precise name-in-title check
        if not any(val.lower() in headline_lower for val in validation_list):
            continue

        parsed_date = entry.get('published_parsed')
        sort_date = datetime(*parsed_date[:6]) if parsed_date else datetime(1900, 1, 1)
        
        source = "Google News"
        if hasattr(entry, 'source'):
            source = entry.source.get('title', 'Google News')
        elif " - " in headline:
            source = headline.split(" - ")[-1]
        
        # NOTE 3: Enforcing credibility right at the search level. If not credible, we skip it.
        if not is_credible_source(source, display_name):
            continue
            
        results.append({
            "sort_key": sort_date,
            "Date": sort_date.strftime('%b %d, %Y'),
            "Company": display_name,
            "Source": source,
            "Headline": headline, 
            "Link": entry.link
        })
    return results

# --- 4. UI ---
st.set_page_config(page_title="REITs News Screener", page_icon="📈", layout="wide")

if 'news_data' not in st.session_state:
    st.session_state.news_data = []

with st.sidebar:
    LOGO_URL = "https://cormark.com/Portals/_default/Skins/Cormark/Images/Cormark_4C_183x42px.png"
    st.image(LOGO_URL)
    st.title("Screener Settings")
    
    # NOTE 4: Removed tier checkboxes (rumors/social/other). Simplified dropdown per instructions.
    dropdown_options = ["--- MASTER VIEWS ---", "Entire Coverage"]
    dropdown_options += ["--- INDIVIDUAL NAMES ---"] + sorted(list(COVERAGE.keys()))
    
    selected_view = st.selectbox("Select Watchlist", options=dropdown_options)
    
    st.divider()
    keyword_filter = st.text_input("🔍 Search Headlines", "").strip().lower()

st.title("Real Estate Coverage News Screener")

# --- BUILD SEARCH TASKS ---
# NOTE 5: Tasks are built using Reference Name, Full Name, AND the Ticker.
search_tasks = []

def build_tasks_for_company(company_key):
    company_data = COVERAGE[company_key]
    ticker = company_data["ticker"]
    full_name = company_data["full_name"]
    ref_names = company_data["ref_names"]
    
    # The validation list ensures the headline actually mentions one of the relevant terms
    validation_list = [ticker, full_name] + ref_names
    
    # 1. Search by full name
    search_tasks.append((full_name, company_key, validation_list))
    
    # 2. Search by reference name(s)
    for ref in ref_names:
        search_tasks.append((ref, company_key, validation_list))
        
    # 3. Second round of search using the Ticker to ensure correct pulls
    search_tasks.append((ticker, company_key, validation_list))

if selected_view == "Entire Coverage":
    for company in COVERAGE:
        build_tasks_for_company(company)
elif selected_view in COVERAGE:
    build_tasks_for_company(selected_view)

# --- EXECUTION ---
if not selected_view.startswith("---"):
    if st.button(f"Search {selected_view}", use_container_width=True):
        all_hits = []
        with st.spinner(f'Searching {selected_view}...'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                future_to_company = {executor.submit(get_google_news, task[0], task[1], task[2]): task[0] for task in search_tasks}
                for future in concurrent.futures.as_completed(future_to_company):
                    # NOTE 6: Extending list keeps all duplicates per instruction. No set() conversion happens here.
                    all_hits.extend(future.result())
        st.session_state.news_data = all_hits

# --- DISPLAY ---
if st.session_state.news_data:
    df = pd.DataFrame(st.session_state.news_data)
    df = df.sort_values(by="sort_key", ascending=False)
    
    if keyword_filter:
        df = df[df['Headline'].str.lower().str.contains(keyword_filter)]

    st.success(f"Found {len(df)} headlines.")
    
    # NOTE 7: Dropped 'Category' column since everything remaining is implicitly credible. Maintained Source and Link.
    st.dataframe(
        df[["Date", "Company", "Source", "Headline", "Link"]], 
        column_config={"Link": st.column_config.LinkColumn("View", display_text="Open")},
        use_container_width=True, 
        hide_index=True
    )
