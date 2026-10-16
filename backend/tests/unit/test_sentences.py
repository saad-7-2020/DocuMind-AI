from documind.chunking.sentences import sentence_spans


def sentences(text: str) -> list[str]:
    return [text[s:e] for s, e in sentence_spans(text)]


def test_splits_on_terminal_punctuation():
    assert sentences("Le contrat est signé. Il entre en vigueur demain! Est-ce clair ? Oui.") == [
        "Le contrat est signé.", "Il entre en vigueur demain!", "Est-ce clair ?", "Oui.",
    ]


def test_french_abbreviations_do_not_split():
    text = "M. Dupont cite l'art. 5 du code, cf. annexe B, p. ex. le Dr. Martin. Fin du texte."
    assert sentences(text) == [
        "M. Dupont cite l'art. 5 du code, cf. annexe B, p. ex. le Dr. Martin.",
        "Fin du texte.",
    ]


def test_lowercase_after_period_does_not_split():
    assert sentences("Version 4.2 du logiciel. suite en minuscule.") == [
        "Version 4.2 du logiciel. suite en minuscule."
    ]


def test_paragraph_breaks_always_split_and_spans_are_trimmed():
    text = "  Titre sans point\n\nPremier paragraphe.  \n\n\nSecond paragraphe.  "
    spans = sentence_spans(text)
    assert [text[s:e] for s, e in spans] == ["Titre sans point", "Premier paragraphe.", "Second paragraphe."]


def test_closing_quotes_stay_with_sentence():
    assert sentences("Il a dit « oui. » Puis il est parti.") == ["Il a dit « oui. »", "Puis il est parti."]
