"""Email acquisition, parsing, archiving, and persistence."""

from shopping.ingestion.pipeline import import_eml, import_gmail_raw_email, import_raw_email

__all__ = ["import_eml", "import_gmail_raw_email", "import_raw_email"]
