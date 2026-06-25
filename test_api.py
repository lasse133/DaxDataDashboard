import json
import time
import random
from datetime import datetime, timedelta
import pandas as pd

from gdeltdoc import GdeltDoc, Filters
# Import the specific exception raised by the library wrapper
from gdeltdoc.errors import RateLimitError
import config

# 1. Configuration Parameters
# target_companies = [f'"{company}"' for company in config.DAX40.keys()]
target_companies = [
    '"Siemens"',
    '"Volkswagen"'
]
trusted_domains = [
    "bloomberg.com", 
    "reuters.com", 
    "finance.yahoo.com", 
    "finanznachrichten.de"
]

start = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
end = datetime.today().strftime("%Y-%m-%d")

# 2. Build the Filters Object
f = Filters(
    keyword=target_companies,
    domain_exact=trusted_domains,
    start_date=start,
    end_date=end,
    num_records=250
)

gd = GdeltDoc()

# 3. Retry Strategy Execution Configuration
MAX_RETRIES = 3
BASE_DELAY = 20  # Delay in seconds to clear the server-side bucket
success = False

print("🚀 Starting the gdeltdoc client engine...")
print(f"Targeting: {target_companies}")

for attempt in range(MAX_RETRIES):
    try:
        print(f"📡 Requesting article matrix (Attempt {attempt + 1}/{MAX_RETRIES})...")
        
        # This is where the script originally crashed
        articles_df = gd.article_search(f)
        
        if articles_df is None or articles_df.empty:
            print("⚠️ Server connected successfully, but 0 articles matched these criteria.")
        else:
            print(f"✅ Data fetched successfully! Processing {len(articles_df)} records...")
            
            # Convert the Pandas DataFrame into an structured dictionary list
            output_data = {
                "articles": articles_df.to_dict(orient="records")
            }
            
            filename = "gdelt_sample.json"
            with open(filename, "w", encoding="utf-8") as file:
                json.dump(output_data, file, indent=4)
                
            print(f"🎉 Success! High-fidelity financial data saved to '{filename}'.")
        
        success = True
        break  # Exit the retry loop upon successful query processing

    except RateLimitError:
        # Catching the exact error from your traceback
        delay = (BASE_DELAY * (2 ** attempt)) + random.uniform(1, 5)
        print(f"❌ [RateLimitError] GDELT's firewall is actively blocking your current network path.")
        
        if attempt < MAX_RETRIES - 1:
            print(f"   Cooling down connection signature... Pausing for {int(delay)} seconds.")
            time.sleep(delay)
        else:
            print("\n🚨 All retry attempts exhausted without clearing the server throttle.")
            
    except Exception as e:
        print(f"❌ Unexpected application exception encountered: {e}")
        break

if not success:
    print("\n💡 Architectural Hint for Development:")
    print("If you cannot clear the API firewall block right now, use your editor to manually")
    print("populate 'gdelt_sample.json' with your previous mockup structure. This ensures your")
    print("Streamlit dashboard UI can still read local files and continue to test your models.")