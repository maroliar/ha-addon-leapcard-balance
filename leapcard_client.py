"""LeapCard client: pure-requests login (Azure B2C flow) + balance/history
extraction via BeautifulSoup."""

import re
import json
import os
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# Used only when running this file directly for manual testing
USERNAME = os.environ.get("LEAPCARD_USERNAME", "")
PASSWORD = os.environ.get("LEAPCARD_PASSWORD", "")

PROTECTED_START_URL = "https://leapcard.ie/en/SelfServices/CardServices/CardOverView.aspx"
HISTORY_URL = "https://leapcard.ie/en/SelfServices/CardServices/ViewJourneyHistory.aspx"

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    ),
}

HISTORY_HEADER_MAP = {
    "Date": "date",
    "Time": "time",
    "Source": "source",
    "Transaction Type": "transaction_type",
    "Amount": "amount",
    "Balance": "balance",
}


class LeapCardLoginError(Exception):
    pass


class LeapCardClient:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update(COMMON_HEADERS)

    def login(self) -> None:
        # Fresh state/nonce comes from letting leapcard.ie redirect us to B2C
        resp1 = self.session.get(PROTECTED_START_URL)

        match_csrf = re.search(r'"csrf"\s*:\s*"([^"]+)"', resp1.text)
        match_trans = re.search(r'"transId"\s*:\s*"([^"]+)"', resp1.text)
        csrf_token = (match_csrf.group(1) if match_csrf
                      else self.session.cookies.get("x-ms-cpim-csrf"))
        tx = match_trans.group(1) if match_trans else None

        if not csrf_token or not tx:
            raise LeapCardLoginError(
                "Could not extract csrf_token/tx from the login page. "
                "The B2C HTML has likely changed format."
            )

        self_asserted_url = (
            f"https://transportforireland.b2clogin.com/transportforireland.onmicrosoft.com/"
            f"B2C_1A_signup_signin/SelfAsserted?tx={tx}&p=B2C_1A_signup_signin"
        )
        resp2 = self.session.post(
            self_asserted_url,
            data={
                "request_type": "RESPONSE",
                "signInName": self.username,
                "password": self.password,
            },
            headers={
                "X-CSRF-TOKEN": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": resp1.url,
            },
        )
        if resp2.status_code != 200 or '"status":"200"' not in resp2.text:
            raise LeapCardLoginError(
                f"Login rejected by B2C (wrong username/password?). "
                f"Response: {resp2.text[:200]}"
            )

        confirmed_url = (
            f"https://transportforireland.b2clogin.com/transportforireland.onmicrosoft.com/"
            f"B2C_1A_signup_signin/api/CombinedSigninAndSignup/confirmed"
            f"?csrf_token={csrf_token}&tx={tx}&p=B2C_1A_signup_signin"
        )
        resp3 = self.session.get(confirmed_url, headers={"Referer": resp1.url})

        form_action_match = re.search(r'''<form[^>]+action=['"]([^'"]+)['"]''', resp3.text)
        hidden_inputs = dict(
            re.findall(r'''<input[^>]+name=['"]([^'"]+)['"][^>]+value=['"]([^'"]*)['"]''', resp3.text)
        )
        if not form_action_match or not hidden_inputs:
            raise LeapCardLoginError(
                "Could not find the final auto-submit form. The B2C flow may have changed."
            )

        # This is what sets the real .AspNet.Cookies session cookie
        self.session.post(form_action_match.group(1), data=hidden_inputs)

        if ".AspNet.Cookies" not in self.session.cookies:
            raise LeapCardLoginError(
                "Login appears to have failed: .AspNet.Cookies cookie was not created."
            )

    def get_name(self) -> str:
        resp = self.session.get(PROTECTED_START_URL)
        soup = BeautifulSoup(resp.text, "html.parser")
        span = soup.find(id="LoginName1")
        return span.get_text(strip=True) if span else ""

    def get_balance(self) -> tuple[str, BeautifulSoup]:
        resp = self.session.get(PROTECTED_START_URL)
        soup = BeautifulSoup(resp.text, "html.parser")
        label = soup.find(id=re.compile(r"lblTravelCreditBalance$"))
        if not label:
            raise LeapCardLoginError(
                "Could not find the balance label on the page. Session may have expired."
            )
        balance_div = label.find_parent("div", class_="row").find(
            "div", class_="float-start"
        )
        return balance_div.get_text(strip=True), soup

    def get_card_number(self) -> str:
        resp = self.session.get(PROTECTED_START_URL)
        soup = BeautifulSoup(resp.text, "html.parser")
        select = soup.find("select", id=re.compile(r"ddlMyCardsList$"))
        if not select:
            raise LeapCardLoginError("Could not find the card selector dropdown.")
        selected_option = select.find("option", selected=True) or select.find("option")
        if not selected_option:
            raise LeapCardLoginError("Card selector dropdown has no options.")
        # Option text looks like "1018366892 - leapcard" - keep just the number
        return selected_option.get_text(strip=True).split(" - ")[0].strip()

    def get_history(self) -> list[dict]:
        resp = self.session.get(HISTORY_URL)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find(id="gvCardJourney")
        if not table:
            raise LeapCardLoginError("History table not found.")

        rows = table.find_all("tr")
        raw_headers = [th.get_text(strip=True) for th in rows[0].find_all("th")]

        history = []
        for row in rows[1:]:
            row_class = " ".join(row.get("class", []))
            if "pager" in row_class.lower():
                continue
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) != len(raw_headers):
                continue
            history.append(
                {HISTORY_HEADER_MAP[h]: c for h, c in zip(raw_headers, cols)}
            )
        return history


def main():
    if not USERNAME or not PASSWORD:
        raise SystemExit(
            "Set LEAPCARD_USERNAME and LEAPCARD_PASSWORD environment variables "
            "before running this file directly."
        )

    client = LeapCardClient(USERNAME, PASSWORD)
    print("Logging in...")
    client.login()
    print("Login OK, extracting data...")

    name = client.get_name()
    balance, _ = client.get_balance()
    card_number = client.get_card_number()
    history = client.get_history()

    data = {
        "name": name,
        "generated_at": datetime.now().strftime("%d/%m/%Y - %H:%M:%S"),
        "balance": balance,
        "card_number": card_number,
        "history": history,
    }

    with open("leap_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n{len(history)} transactions found. Saved to leap_data.json")


if __name__ == "__main__":
    main()