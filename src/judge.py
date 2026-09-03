"""Run the Judge instrument. Parse XML output."""

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path

from src.api import call_api
from src.logger import log_api_call


@dataclass
class Divergence:
    id: str
    location: str
    response_a: str
    response_b: str
    nature: str
    specificity: str


@dataclass
class JudgeOutput:
    convergence: str
    divergences: list[Divergence]
    raw_xml: str
    parse_success: bool
    parse_error: str | None
    judge_model: str
    tokens_input: int
    tokens_output: int


def _escape_bare_ampersands(text: str) -> str:
    """Replace bare & that aren't part of XML entities (&amp; &lt; &gt; &quot; &apos; &#...;)."""
    return re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[\da-fA-F]+;)", "&amp;", text)


def _parse_judge_xml_fallback(xml_text: str) -> tuple[str, list[Divergence]]:
    """Regex fallback parser for malformed XML (e.g. mismatched closing tags)."""
    # Extract convergence
    conv_match = re.search(r"<convergence>(.*?)</convergence>", xml_text, re.DOTALL)
    convergence = conv_match.group(1).strip() if conv_match else ""

    # Extract each divergence block
    divergences = []
    div_blocks = re.findall(r"<divergence[^>]*>(.*?)</divergence>", xml_text, re.DOTALL)
    if not div_blocks and not conv_match:
        raise ValueError("Fallback parser found no <convergence> or <divergence> blocks")

    for block in div_blocks:
        # Extract id from the divergence tag attributes
        id_attr_match = re.search(r'<divergence\s+id="([^"]*)"', xml_text)
        div_id = id_attr_match.group(1) if id_attr_match else ""

        def _extract(tag: str, text: str) -> str:
            m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
            if not m:
                # Also try mismatched closing tags: <tag>...</any_tag>
                m = re.search(rf"<{tag}>(.*?)</\w+>", text, re.DOTALL)
            return m.group(1).strip() if m else ""

        divergences.append(Divergence(
            id=div_id,
            location=_extract("location", block),
            response_a=_extract("response_a", block),
            response_b=_extract("response_b", block),
            nature=_extract("nature", block),
            specificity=_extract("specificity", block),
        ))

    return convergence, divergences


def _parse_judge_xml(raw: str) -> tuple[str, list[Divergence]]:
    """Extract comparison XML, parse convergence and divergences."""
    match = re.search(r"<comparison>(.*?)</comparison>", raw, re.DOTALL)
    if not match:
        raise ValueError("No <comparison> block found in judge output")

    inner = _escape_bare_ampersands(match.group(1))
    xml_str = "<comparison>" + inner + "</comparison>"

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return _parse_judge_xml_fallback(xml_str)

    convergence_el = root.find("convergence")
    convergence = (convergence_el.text or "").strip() if convergence_el is not None else ""

    divergences = []
    for div_el in root.findall("divergence"):
        div_id = div_el.get("id", "")
        location = (div_el.findtext("location") or "").strip()
        response_a = (div_el.findtext("response_a") or "").strip()
        response_b = (div_el.findtext("response_b") or "").strip()
        nature = (div_el.findtext("nature") or "").strip()
        specificity = (div_el.findtext("specificity") or "").strip()
        divergences.append(Divergence(
            id=div_id,
            location=location,
            response_a=response_a,
            response_b=response_b,
            nature=nature,
            specificity=specificity,
        ))

    return convergence, divergences


def run_judge(
    response_a: str,
    response_b: str,
    judge_prompt_path: Path,
    judge_model: str,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    log_path: Path | None = None,
    phase: str = "",
    problem_id: str = "",
) -> JudgeOutput:
    template = Path(judge_prompt_path).read_text()
    prompt = template.replace("{{RESPONSE_A}}", response_a).replace("{{RESPONSE_B}}", response_b)

    api_response = None
    try:
        api_response = call_api(judge_model, prompt, temperature=0,
                                max_retries=max_retries, backoff_base=backoff_base,
                                seed=42)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        if log_path:
            log_api_call(log_path, judge_model, 0, phase,
                         "judge", problem_id, prompt, api_response, str(e))
        raise

    if log_path:
        log_api_call(log_path, judge_model, 0, phase,
                     "judge", problem_id, prompt, api_response)

    raw_xml = api_response.content
    try:
        convergence, divergences = _parse_judge_xml(raw_xml)
        return JudgeOutput(
            convergence=convergence,
            divergences=divergences,
            raw_xml=raw_xml,
            parse_success=True,
            parse_error=None,
            judge_model=judge_model,
            tokens_input=api_response.tokens_input,
            tokens_output=api_response.tokens_output,
        )
    except Exception as e:
        return JudgeOutput(
            convergence="",
            divergences=[],
            raw_xml=raw_xml,
            parse_success=False,
            parse_error=str(e),
            judge_model=judge_model,
            tokens_input=api_response.tokens_input,
            tokens_output=api_response.tokens_output,
        )


def save_judge_output(output: JudgeOutput, filepath: Path) -> None:
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(output)
    filepath.write_text(json.dumps(data, indent=2))


def load_judge_output(filepath: Path) -> JudgeOutput:
    data = json.loads(Path(filepath).read_text())
    divergences = [Divergence(**d) for d in data["divergences"]]
    return JudgeOutput(
        convergence=data["convergence"],
        divergences=divergences,
        raw_xml=data["raw_xml"],
        parse_success=data["parse_success"],
        parse_error=data["parse_error"],
        judge_model=data["judge_model"],
        tokens_input=data["tokens_input"],
        tokens_output=data["tokens_output"],
    )
