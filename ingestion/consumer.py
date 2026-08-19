"""Curated consumer single-name universes shared by baskets and exports.

The S&P 500 cohorts provide a complete, reproducible large-cap base.  A small
completion cohort adds liquid category leaders that matter to consumer reads
but sit outside the index (MTN, CAVA, CELH, ELF, etc.).  Labels live beside the
symbols so Theme Returns and the synthetic equal-weight baskets cannot drift.
"""

# Current S&P 500 Consumer Discretionary members.  Keep this list in sync with
# data/tickers.csv; tests intentionally fail when the index membership changes.
CONSUMER_DISCRETIONARY_SP500 = [
    ("AMZN", "Amazon · AMZN"), ("TSLA", "Tesla · TSLA"),
    ("HD", "Home Depot · HD"), ("MCD", "McDonald's · MCD"),
    ("TJX", "TJX Companies · TJX"), ("BKNG", "Booking Holdings · BKNG"),
    ("SBUX", "Starbucks · SBUX"), ("LOW", "Lowe's · LOW"),
    ("MAR", "Marriott · MAR"), ("ROST", "Ross Stores · ROST"),
    ("RCL", "Royal Caribbean · RCL"), ("ABNB", "Airbnb · ABNB"),
    ("CMG", "Chipotle · CMG"), ("DASH", "DoorDash · DASH"),
    ("ORLY", "O'Reilly Automotive · ORLY"), ("HLT", "Hilton · HLT"),
    ("AZO", "AutoZone · AZO"), ("NKE", "Nike · NKE"),
    ("LULU", "Lululemon · LULU"), ("DRI", "Darden Restaurants · DRI"),
    ("YUM", "Yum! Brands · YUM"), ("DECK", "Deckers · DECK"),
    ("GM", "General Motors · GM"), ("F", "Ford · F"),
    ("CCL", "Carnival · CCL"), ("LVS", "Las Vegas Sands · LVS"),
    ("NCLH", "Norwegian Cruise Line · NCLH"), ("MGM", "MGM Resorts · MGM"),
    ("WYNN", "Wynn Resorts · WYNN"), ("EXPE", "Expedia · EXPE"),
    ("DPZ", "Domino's · DPZ"), ("ULTA", "Ulta Beauty · ULTA"),
    ("TSCO", "Tractor Supply · TSCO"), ("GPC", "Genuine Parts · GPC"),
    ("WSM", "Williams-Sonoma · WSM"), ("BBY", "Best Buy · BBY"),
    ("EBAY", "eBay · EBAY"), ("HAS", "Hasbro · HAS"),
    ("GRMN", "Garmin · GRMN"), ("CVNA", "Carvana · CVNA"),
    ("TPR", "Tapestry · TPR"), ("RL", "Ralph Lauren · RL"),
    ("DHI", "D.R. Horton · DHI"), ("LEN", "Lennar · LEN"),
    ("PHM", "PulteGroup · PHM"), ("NVR", "NVR · NVR"),
    ("APTV", "Aptiv · APTV"),
]

# Liquid mid-cap and recent-growth category leaders omitted by an S&P 500-only
# screen.  This is deliberately selective rather than the whole completion
# index, which would turn the rail into hundreds of thinly traded names.
CONSUMER_DISCRETIONARY_EXTENDED = [
    ("MTN", "Vail Resorts · MTN"), ("CHDN", "Churchill Downs · CHDN"),
    ("CAVA", "Cava · CAVA"), ("TXRH", "Texas Roadhouse · TXRH"),
    ("WING", "Wingstop · WING"), ("BROS", "Dutch Bros · BROS"),
    ("PLNT", "Planet Fitness · PLNT"), ("ONON", "On Holding · ONON"),
    ("BIRK", "Birkenstock · BIRK"), ("CROX", "Crocs · CROX"),
    ("ANF", "Abercrombie & Fitch · ANF"), ("DKS", "Dick's Sporting Goods · DKS"),
    ("TOL", "Toll Brothers · TOL"), ("RIVN", "Rivian · RIVN"),
]

CONSUMER_DISCRETIONARY = (
    CONSUMER_DISCRETIONARY_SP500 + CONSUMER_DISCRETIONARY_EXTENDED
)

# Current S&P 500 Consumer Staples members.
CONSUMER_STAPLES_SP500 = [
    ("COST", "Costco · COST"), ("WMT", "Walmart · WMT"),
    ("PG", "Procter & Gamble · PG"), ("KO", "Coca-Cola · KO"),
    ("PEP", "PepsiCo · PEP"), ("PM", "Philip Morris · PM"),
    ("MO", "Altria · MO"), ("MDLZ", "Mondelez · MDLZ"),
    ("MNST", "Monster Beverage · MNST"), ("CL", "Colgate-Palmolive · CL"),
    ("KDP", "Keurig Dr Pepper · KDP"), ("TGT", "Target · TGT"),
    ("KR", "Kroger · KR"), ("SYY", "Sysco · SYY"),
    ("ADM", "Archer-Daniels-Midland · ADM"), ("BF-B", "Brown-Forman · BF-B"),
    ("BG", "Bunge Global · BG"), ("CASY", "Casey's General Stores · CASY"),
    ("CHD", "Church & Dwight · CHD"), ("CLX", "Clorox · CLX"),
    ("DG", "Dollar General · DG"), ("DLTR", "Dollar Tree · DLTR"),
    ("EL", "Estée Lauder · EL"), ("GIS", "General Mills · GIS"),
    ("HRL", "Hormel Foods · HRL"), ("HSY", "Hershey · HSY"),
    ("KHC", "Kraft Heinz · KHC"), ("KMB", "Kimberly-Clark · KMB"),
    ("KVUE", "Kenvue · KVUE"), ("MKC", "McCormick · MKC"),
    ("SJM", "J.M. Smucker · SJM"), ("STZ", "Constellation Brands · STZ"),
    ("TAP", "Molson Coors · TAP"), ("TSN", "Tyson Foods · TSN"),
]

CONSUMER_STAPLES_EXTENDED = [
    ("CELH", "Celsius · CELH"), ("ELF", "e.l.f. Beauty · ELF"),
    ("COTY", "Coty · COTY"), ("SAM", "Boston Beer · SAM"),
    ("USFD", "US Foods · USFD"), ("PFGC", "Performance Food Group · PFGC"),
    ("BJ", "BJ's Wholesale Club · BJ"), ("SFM", "Sprouts Farmers Market · SFM"),
    ("CAG", "Conagra Brands · CAG"), ("CPB", "Campbell's · CPB"),
    ("POST", "Post Holdings · POST"), ("PPC", "Pilgrim's Pride · PPC"),
]

CONSUMER_STAPLES = CONSUMER_STAPLES_SP500 + CONSUMER_STAPLES_EXTENDED

# Retained as a useful semantic subset for tests and downstream callers.
RESTAURANTS = [
    (ticker, label) for ticker, label in CONSUMER_DISCRETIONARY_SP500
    if ticker in {"SBUX", "CMG", "MCD", "YUM", "DRI", "DPZ"}
]


def tickers(records):
    return [ticker for ticker, _ in records]
