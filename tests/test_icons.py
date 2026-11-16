import json

import pytest

from infographics.rag.icons import INDEX_PATH, build_index, clean_svg, load_icons

SVG = '<svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">\n<path d="M0 0" fill="currentColor"/>\n</svg>\n'


def test_clean_svg_drops_fixed_size_but_keeps_viewbox():
    cleaned = clean_svg(SVG)
    assert 'width="48"' not in cleaned and 'height="48"' not in cleaned
    assert 'viewBox="0 0 48 48"' in cleaned
    assert cleaned == '<svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M0 0" fill="currentColor"/></svg>'


def test_clean_svg_rejects_non_svg():
    with pytest.raises(ValueError):
        clean_svg("<html></html>")


@pytest.fixture
def fake_repo(tmp_path):
    icons = tmp_path / "public" / "icons"
    (icons / "svg" / "filled" / "devices").mkdir(parents=True)
    (icons / "svg" / "filled" / "devices" / "syringe.svg").write_text(SVG)
    (icons / "meta-data.json").write_text(json.dumps([
        {"id": "syringe", "category": "devices", "path": "devices/syringe",
         "tags": ["Injection", "Needle", "dhis2:syringe"], "title": "Syringe", "formats": ["48px"]},
    ]))
    return tmp_path


def test_index_keeps_descriptive_tags_only(fake_repo, tmp_path):
    index = build_index(fake_repo, supplementary_dir=None)
    assert index["license"] == "CC0 1.0" and len(index["commit"]) == 40
    (icon,) = index["icons"]
    assert icon["id"] == "devices/syringe"
    assert icon["tags"] == ("Injection", "Needle")

    path = tmp_path / "index.json"
    path.write_text(json.dumps(index))
    loaded = load_icons(path)["devices/syringe"]
    assert loaded.description() == "Syringe, Injection, Needle"


def test_missing_index_says_how_to_build_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_icon_index"):
        load_icons(tmp_path / "index.json")


@pytest.mark.skipif(not INDEX_PATH.exists(), reason="icon index is built locally, not in git")
def test_built_index_has_the_hiv_icons_and_the_supplementary_ones():
    icons = load_icons()
    assert len(icons) == 776 + 10
    for icon_id in ["conditions/ribbon", "diagnostics/hiv-self_test", "contraceptives/male-condom",
                    "devices/syringe", "medications/pill-1", "people/person", "supplementary/clock"]:
        assert 'fill="currentColor"' in icons[icon_id].svg
    assert icons["supplementary/clock"].source == "material-symbols"
    assert icons["devices/syringe"].source == "healthicons"


def test_supplementary_icons_draw_in_current_colour():
    from infographics.rag.icons import SUPPLEMENTARY, supplementary_icons

    icons = supplementary_icons()
    assert len(icons) == len(SUPPLEMENTARY) == 10
    for icon in icons:
        assert icon.category == "supplementary"
        assert 'width="48"' not in icon.svg and 'viewBox="0 -960 960 960"' in icon.svg
        assert icon.svg.count("<path") == icon.svg.count('fill="currentColor"')
