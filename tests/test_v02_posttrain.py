"""V0.2 post-training pipeline + evaluation suites. No model weights: a fake
back-end stands in for generation/loss, and a tiny fake adapter for integrity."""

import json
import re

import pytest
import torch
from safetensors.torch import save_file

import scripts.posttrain_v02 as pt
from rupsaa.config import PROJECT_ROOT
from rupsaa.personality.system_prompt import BASE_PERSONA, build_system_prompt
from rupsaa.personality.system_prompt_v02 import V02_SYSTEM_PROMPT

EVAL_DIR = PROJECT_ROOT / "data/production/evaluation/rupsaa_v0.2"
FROZEN = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training/frozen_records.jsonl"
suites = pytest.mark.skipif(not (EVAL_DIR / "eval_manifests.json").exists(), reason="V0.2 eval suites not built")


class FakeBackend:
    def __init__(self, reply="Eta mane ekta kichu kore, jate climax deri hoy."):
        self.reply, self.calls = reply, []

    def generate(self, variant, messages, seed):
        self.calls.append((variant, messages))
        return self.reply

    def loss(self, variant, messages):
        return {"rupsaa_v02": 1.0, "rupsaa_v01": 1.5, "base": 3.0}[variant], 10


# --- evaluation suites ------------------------------------------------------------------------

@suites
def test_terminology_suite_is_unseen_and_runtime_formatted():
    cases = [json.loads(line) for line in open(EVAL_DIR / "terminology_generalization.jsonl", encoding="utf-8")]
    assert 20 <= len(cases) <= 30
    assert {c["language"] for c in cases} == {"banglish", "bn", "en", "mixed"}
    blob = "\n".join(m["content"].lower() for line in open(FROZEN, encoding="utf-8") for m in json.loads(line)["messages"])
    for c in cases:
        assert c["system_v02"] == build_system_prompt(prompt_version="v0.2", terminology_context=c["terminology_context"])
        assert c["terminology_context"].startswith("Term: ") and "\nDefinition: " in c["terminology_context"]
        names = [c["term"]] + re.findall(r"^Also called / asked as: (.*)$", c["terminology_context"], re.M)[0].split(", ") \
            if "Also called" in c["terminology_context"] else [c["term"]]
        for name in names:
            assert not re.search(r"(?<![a-zঀ-৿])" + re.escape(name.lower()) + r"(?![a-zঀ-৿])", blob), name
        assert len(c["turns"]) == len(c["expect"])
    behaviours = {b for c in cases for b in c["behaviours"]}
    for needed in ("typo", "unseen_alias", "concise", "detailed", "simple_kore_bolo", "short_kore_bolo",
                   "bengali_followup", "banglish_followup", "language_switch_to_bengali",
                   "language_switch_to_english", "language_switch_to_banglish"):
        assert needed in behaviours


@suites
def test_eval_manifests_full_and_clean_subsets():
    m = json.loads((EVAL_DIR / "eval_manifests.json").read_text(encoding="utf-8"))
    frozen = {json.loads(line)["id"]: json.loads(line)["split"] for line in open(FROZEN, encoding="utf-8")}
    assert m["created_from"]["v01_train_records"] == 772
    for split, full, clean in (("validation", 77, 41), ("test", 76, 38)):
        a, b = m["A_full"][split], m["B_clean_v01_vs_v02"][split]
        assert (a["count"], b["count"]) == (full, clean)
        assert all(frozen[i] == split for i in a["ids"])
        excluded = set(b["excluded_seen_in_v01_training"]["ids"])
        assert set(b["ids"]) | excluded == set(a["ids"]) and not set(b["ids"]) & excluded


@suites
def test_live_checks_cover_the_ten_owner_prompts():
    checks = json.loads((EVAL_DIR / "live_behavior_checks.json").read_text(encoding="utf-8"))
    firsts = [c["turns"][0] for c in checks]
    assert len(checks) == 10
    for p in ("hi, tumi kemon acho?", "achcha", "Strip mane ki?", "foreplay ki?", "amar favourite color blue"):
        assert p in firsts


# --- pure logic ---------------------------------------------------------------------------------

def test_check_turn_flags():
    ok = pt.check_turn("Eta mane climax deri kora.", {"script": "latin", "max_chars": 100, "grounding_any": ["climax"]}, None, ["honestly"])
    assert ok["pass"]
    bad = pt.check_turn("Honestly, এটা একটা জিনিস।", {"script": "latin", "grounding_any": ["climax"]}, None, ["honestly"])
    assert not bad["pass"] and not bad["checks"]["script"] and not bad["checks"]["no_forbidden_phrase"]
    longer = pt.check_turn("x" * 50, {"shorter_than_previous": True}, "x" * 10, [])
    assert not longer["checks"]["shorter_than_previous"]


def test_gate_requires_beating_v01_and_base_on_clean_test():
    loss = {"B_clean_v01_vs_v02": {"test": {"overall": {"loss_rupsaa_v02": 1.0, "loss_rupsaa_v01": 1.5, "loss_base": 3.0}}}}
    term = {"pass_rate": {"rupsaa_v02": 0.9, "rupsaa_v01": 0.5}}
    live = {"script_pass": {"rupsaa_v02": 10}, "catchphrases": {"rupsaa_v02": {"honestly": 0}}}
    assert pt.gate({"passed": True}, loss, term, live)["recommend_integration"]
    worse = {"B_clean_v01_vs_v02": {"test": {"overall": {"loss_rupsaa_v02": 1.6, "loss_rupsaa_v01": 1.5, "loss_base": 3.0}}}}
    assert not pt.gate({"passed": True}, worse, term, live)["recommend_integration"]
    assert not pt.gate({"passed": False}, loss, term, live)["recommend_integration"]
    tic = {"script_pass": {"rupsaa_v02": 10}, "catchphrases": {"rupsaa_v02": {"honestly": 2}}}
    assert not pt.gate({"passed": True}, loss, term, tic)["recommend_integration"]


def _fake_run(tmp_path, best_step=40, root_differs=False):
    adapter = tmp_path / "rupsaa-v0.2"
    ckpt = adapter / f"checkpoint-{best_step}"
    ckpt.mkdir(parents=True)
    tensors = {"a": torch.ones(2, 2), "b": torch.zeros(3)}
    save_file(tensors, str(ckpt / "adapter_model.safetensors"))
    save_file({"a": torch.ones(2, 2) * (2 if root_differs else 1), "b": torch.zeros(3)}, str(adapter / "adapter_model.safetensors"))
    (adapter / "adapter_config.json").write_text(json.dumps({
        "base_model_name_or_path": "Qwen/Qwen2.5-7B-Instruct", "peft_type": "LORA", "r": 16, "lora_alpha": 32,
        "lora_dropout": 0.05, "target_modules": sorted(pt.EXPECTED_TARGETS)}), encoding="utf-8")
    (adapter / "trainer_config.yaml").write_text(f"dataset: rupsaa_v0.2_train\noutput_dir: {adapter}\n", encoding="utf-8")
    (adapter / "trainer_state.json").write_text(json.dumps({
        "best_model_checkpoint": str(ckpt), "best_metric": 1.2, "global_step": 164, "max_steps": 164, "num_train_epochs": 2,
        "log_history": [{"step": 20, "epoch": 0.24, "eval_loss": 1.5}, {"step": 40, "epoch": 0.49, "eval_loss": 1.2},
                        {"step": 60, "epoch": 0.73, "eval_loss": 1.3}, {"step": 10, "epoch": 0.1, "loss": 2.0}]}), encoding="utf-8")
    return adapter


def test_locate_best_checkpoint_and_integrity(tmp_path):
    adapter = _fake_run(tmp_path)
    best = pt.locate_best_checkpoint(adapter)
    assert best["best_checkpoint_exists"] and best["best_matches_lowest_eval"]
    assert best["lowest_logged_eval"]["step"] == 40 and len(best["eval_curve"]) == 3
    integrity = pt.verify_adapter(adapter, best)
    assert integrity["passed"], integrity["checks"]


def test_integrity_fails_if_root_adapter_is_not_the_best_checkpoint(tmp_path):
    adapter = _fake_run(tmp_path, root_differs=True)
    integrity = pt.verify_adapter(adapter, pt.locate_best_checkpoint(adapter))
    assert not integrity["passed"] and not integrity["checks"]["root_adapter_is_best_checkpoint"]["pass"]


def test_locate_best_checkpoint_requires_a_finished_run(tmp_path):
    with pytest.raises(FileNotFoundError):
        pt.locate_best_checkpoint(tmp_path / "missing")


# --- suite runners with the fake back-end -----------------------------------------------------

@suites
def test_terminology_runner_uses_each_models_serving_prompt():
    cases = [json.loads(line) for line in open(EVAL_DIR / "terminology_generalization.jsonl", encoding="utf-8")][:4]
    backend = FakeBackend()
    out = pt.run_terminology_suite(backend, cases)
    assert set(out["pass_rate"]) == set(pt.VARIANTS)
    systems = {(v, m[0]["content"].split("\n\n")[0]) for v, m in backend.calls}
    assert ("rupsaa_v02", V02_SYSTEM_PROMPT.split("\n\n")[0]) in systems
    assert ("rupsaa_v01", BASE_PERSONA.strip().split("\n\n")[0]) in systems
    assert all("Reference terminology:\nTerm: " in m[0]["content"] for _, m in backend.calls)
    follow = [m for v, m in backend.calls if v == "rupsaa_v02" and len(m) > 2]  # follow-up keeps history + term block
    assert follow and follow[0][-2]["role"] == "assistant"


@suites
def test_live_runner_uses_real_runtime_routing():
    checks = {c["id"]: c for c in json.loads((EVAL_DIR / "live_behavior_checks.json").read_text(encoding="utf-8"))}
    out = pt.run_live_checks(FakeBackend("Blue bolechile."), [checks["live-04"], checks["live-09"]], variants=("rupsaa_v02",))
    strip, memory = out["cases"]
    assert strip["runs"]["rupsaa_v02"]["turns"][0]["route"] == "terminology"
    assert "term-strip_stripping" in strip["runs"]["rupsaa_v02"]["turns"][0]["terms_used"]
    assert memory["runs"]["rupsaa_v02"]["turns"][1]["route"] == "memory"


@suites
def test_report_renders(tmp_path):
    adapter = _fake_run(tmp_path)
    best = pt.locate_best_checkpoint(adapter)
    cases = [json.loads(line) for line in open(EVAL_DIR / "terminology_generalization.jsonl", encoding="utf-8")][:2]
    term = pt.run_terminology_suite(FakeBackend(), cases)
    result = {"timestamp": "t", "best_checkpoint": best, "integrity": pt.verify_adapter(adapter, best),
              "training_commit": {"recorded": False}, "terminology": term}
    result["gate"] = pt.gate(result["integrity"], None, term, None)
    md = pt.render_report(result)
    assert "Best checkpoint" in md and "Unseen-terminology" in md and cases[0]["id"] in md
