from app.modules.records.query_expand import expand_query_terms


def test_expand_includes_devanagari_for_latin_sugar() -> None:
    terms = expand_query_terms("sugar levels")
    assert "sugar levels" in terms
    assert "मधुमेह" in terms


def test_expand_drug_brand_to_generic() -> None:
    terms = expand_query_terms("glycomet")
    assert "metformin" in terms
