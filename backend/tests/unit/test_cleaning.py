from documind.domain.models import ExtractionMethod, PageText
from documind.ingestion.cleaning import clean_pages, clean_text


def test_ligatures_and_nbsp_are_normalized():
    assert clean_text("Le ﬁchier : conﬁdentiel !") == "Le fichier : confidentiel !"


def test_dehyphenation_only_before_lowercase():
    assert clean_text("informa-\ntion importante") == "information importante"
    assert clean_text("Jean-\nPierre") == "Jean-\nPierre"


def test_whitespace_collapsed():
    assert clean_text("a   b\t c\n\n\n\nd  ") == "a b c\n\nd"


def test_running_headers_footers_and_page_numbers_removed():
    raw = [
        PageText(i, f"ACME SA - Rapport annuel 2025\nContenu de la page {i}.\nPage {i} / 4",
                 ExtractionMethod.TEXT_LAYER)
        for i in range(1, 5)
    ]
    cleaned = clean_pages(raw)
    assert [p.text for p in cleaned] == [f"Contenu de la page {i}." for i in range(1, 5)]


def test_headers_kept_when_too_few_pages():
    raw = [PageText(1, "Titre\nTexte.", ExtractionMethod.PLAIN), PageText(2, "Titre\nAutre.", ExtractionMethod.PLAIN)]
    assert [p.text for p in clean_pages(raw)] == ["Titre\nTexte.", "Titre\nAutre."]
