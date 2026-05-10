"""
Fuzzy Matcher Component for Mapping Bookmaker Team Names to API-Football Names.
"""
from typing import Optional, Dict
import logging
import re
from fuzzywuzzy import fuzz, process
from cachetools import TTLCache

logger = logging.getLogger(__name__)

class TeamMatcher:
    def __init__(self, db):
        self.db = db
        # Quick mapping memory (LRU or TTL caching to prevent DB hits)
        self.cache = TTLCache(maxsize=1000, ttl=86400) # 24h cache
        
        # Load API-Football team lists once 
        self.api_teams = self._load_known_teams()
        
        # We store known aliasing for tough exceptions that fuzz doesn't catch
        self.aliases = {
            "man utd": "Manchester United",
            "manchester utd": "Manchester United",
            "man city": "Manchester City",
            "spurs": "Tottenham Hotspur",
            "psg": "Paris Saint Germain",
            "bayern munich": "Bayern Munich",
            "fc bayern munchen": "Bayern Munich"
        }

    def _load_known_teams(self) -> Dict[str, Dict]:
        """Loads teams from DB mapping them by name string for rapid matching."""
        rows = self.db.get_all_teams() if self.db else []
        known_teams: Dict[str, Dict] = {}
        for row in rows:
            if not row.get("name"):
                continue
            known_teams[row["name"]] = row
        return known_teams

    @staticmethod
    def _normalize_name(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()

    def match_team(self, scrape_name: str, threshold: int = 80) -> Optional[Dict]:
        """
        Attempts to fuzzy match scraped team name to known database names.
        Returns the mapped ID if confidence is above threshold.
        """
        if not self.api_teams:
            self.api_teams = self._load_known_teams()

        normalized_name = self._normalize_name(scrape_name)
        if not normalized_name:
            return None
        
        # 1. Check cache
        if normalized_name in self.cache:
            return self.cache[normalized_name]
            
        # 2. Check strict aliases
        if normalized_name in self.aliases:
            mapped_name = self.aliases[normalized_name]
            mapped = self.api_teams.get(mapped_name)
            if mapped:
                result = {"name": mapped_name, **mapped}
                self.cache[normalized_name] = result
                return result
        
        for canonical_name, team_data in self.api_teams.items():
            if normalized_name == self._normalize_name(canonical_name):
                result = {"name": canonical_name, **team_data}
                self.cache[normalized_name] = result
                return result
            
        # 3. Apply Fuzzy Matching using process.extractOne
        team_names = list(self.api_teams.keys())
        if not team_names:
            return None
            
        extracted = process.extractOne(scrape_name, team_names, scorer=fuzz.token_sort_ratio)
        if not extracted:
            return None
        best_match, score = extracted
        
        if score >= threshold:
            result = {"name": best_match, **self.api_teams[best_match]}
            self.cache[normalized_name] = result
            logger.info(f"Fuzzy Matched: '{scrape_name}' -> '{best_match}' (Score: {score})")
            return result
        else:
            logger.warning(f"Could not reliably match team '{scrape_name}'. Best was '{best_match}' (Score: {score})")
            return None
