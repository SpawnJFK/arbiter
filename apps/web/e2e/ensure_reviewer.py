"""E2E helper: make sure a second, SENIOR, active demo reviewer exists.

The demo seed (`arbiter.cli seed-demo`) creates one reviewer at level "reviewer". Workflows with
`second_review` need a different reviewer at level senior or above, so the E2E creates one here
through the backend's own service functions (no SQL, nothing in services/api changes).

Usage: python e2e/ensure_reviewer.py <email> <password>
Needs ARBITER_DATABASE_URL like the API. Prints the profile id. Fictional demo data only.
"""

from __future__ import annotations

import pathlib
import sys

API_DIR = pathlib.Path(__file__).resolve().parents[3] / "services" / "api"
sys.path.insert(0, str(API_DIR))

from sqlalchemy import select  # noqa: E402

from arbiter.community import profiles, scoring  # noqa: E402
from arbiter.db import session_scope  # noqa: E402
from arbiter.models import ReviewerPair, User  # noqa: E402


def main(email: str, password: str) -> None:
    with session_scope() as s:
        user = s.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user, profile = profiles.apply(
                s,
                name="Demo Senior Reviewer",
                email=email,
                password=password,
                country="DE",
                pairs=[{"source_lang": "en", "target_lang": "de"}, {"source_lang": "en", "target_lang": "sr"}],
                domains=["pharma", "software"],
            )
        else:
            profile = profiles.profile_for_user(s, user.id)
        profile.status = "active"
        profile.level = "senior"
        if not profile.score:
            profile.score = scoring.compute([])
        for pair in s.execute(select(ReviewerPair).where(ReviewerPair.reviewer_id == profile.id)).scalars():
            pair.status = "active"
            pair.retest_after = None
            pair.score = pair.score or scoring.compute([])
        if not profiles.tax_info_complete(profile):
            profiles.update_tax_info(
                s,
                profile,
                legal_name="Demo Senior Reviewer",
                tax_id="DEMO-0001",
                address="2 Demo Street, Demo City",
                date_of_birth="1985-01-01",
                payout_method="sepa",
                payout_details={"iban": "DEMO-NOT-A-REAL-ACCOUNT"},
            )
        print(profile.id)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
