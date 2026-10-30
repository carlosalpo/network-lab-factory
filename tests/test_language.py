"""Saved Spanish recipes remain valid and display English without being rewritten."""

import copy
import json

import pytest

from netlab.catalog_render import eve_xml
from netlab.language import english
from netlab.recipes import make_catalog_plan, validate_catalog_plan


def test_saved_recipe_translation_preserves_identity_and_mutation_guards():
    plan = make_catalog_plan("A07", "saved-workshop")
    plan.update(
        title="Troubleshooting guiado",
        prepare="Referencia OSPF comprobada; la falla se introduce después mediante una acción explícita.",
        exercise="Diagnosticar y reparar una falla después de comprobar la base.",
    )
    before = json.dumps(plan, sort_keys=True)
    assert validate_catalog_plan(plan) == plan
    assert english(plan["title"]) == "Guided troubleshooting"
    assert "Guided troubleshooting" in eve_xml(plan)
    assert english(plan["actions"][0]["label"]) == "Inject link fault"
    assert json.dumps(plan, sort_keys=True) == before
    changed = copy.deepcopy(plan)
    changed["nodes"][0]["base"].append("shutdown")
    with pytest.raises(ValueError, match="modified"):
        validate_catalog_plan(changed)
    assert english("My custom exercise") == "My custom exercise"
