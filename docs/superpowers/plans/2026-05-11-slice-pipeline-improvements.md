# Slice Pipeline Improvement: Analysis Quality, Efficiency, UX

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the broken Chinese keyword extractor, make quality scoring actually differentiate slices, cache Whisper model to avoid reloads, and add Dashboard auto-refresh + refined-slice markers.

**Why:** The local-audio slice pipeline runs end-to-end but produces undifferentiated results: keyword extraction returns empty lists (the `\b` anchor doesn't work for Chinese), `audio_quality` is always 0.5 so quality filtering is a no-op, Whisper reloads on every slice, and Dashboard needs manual refresh.

**Architecture:** Keep the existing heuristic-based analysis approach (no new dependencies like jieba). Improve the signal quality within the existing framework so that `quality_score`, `retain_recommendation`, and title generation produce meaningful variation.

**Tech Stack:** Python stdlib `re` + `collections`, `shutil`, `shutil.rmtree`, vanilla JS `setInterval` + `visibilitychange`.

---

## File Structure

- Modify: `src/autoslice/mllm_sdk/audio_analyzer.py` — keyword extraction, quality scoring, Whisper cache, cleanup
- Modify: `src/autoslice/mllm_sdk/multi_modal_analyzer.py` — `combine_analysis` retain logic, `_build_audio_title` fallback
- Modify: `src/burn/feedback_refine.py` — write `refined: true` marker
- Modify: `frontend/app.js` — auto-refresh, refined badge
- Modify: `frontend/styles.css` — `.refined` style
- Add tests to: `tests/test_autoslice.py`

---

### Task 1: Fix Chinese Keyword Extraction

**Files:**
- Modify: `src/autoslice/mllm_sdk/audio_analyzer.py`
- Test: `tests/test_autoslice.py`

**Problem:** `extract_keywords` uses regex `\b[一-龥]{2,4}\b` which returns empty for Chinese because `\b` is an ASCII word boundary.

- [ ] **Step 1: Rewrite `extract_keywords`**

Replace the current implementation with a sliding-window approach plus stopword filtering:

```python
_STOPWORDS = set("的了是在我你他她它们这那个一不要会就能着过又很都也还让被把向从与而为及但虽却")

def extract_keywords(text: str, max_keywords: int = 5) -> list:
    from collections import Counter
    phrases = Counter()
    for n in range(2, 5):
        for i in range(len(text) - n + 1):
            w = text[i:i+n]
            if re.match(r'^[一-龥]+$', w) and not any(c in _STOPWORDS for c in w):
                phrases[w] += 1
    seen = set()
    result = []
    for w, _ in phrases.most_common():
        if not any(w in s for s in seen):
            seen.add(w)
            result.append(w)
        if len(result) >= max_keywords:
            break
    return result
```

- [ ] **Step 2: Add test**

Add to `tests/test_autoslice.py`:

```python
class TestKeywordExtraction(unittest.TestCase):
    def test_extracts_chinese_keywords(self):
        from src.autoslice.mllm_sdk.audio_analyzer import extract_keywords
        result = extract_keywords("今天打了一把排位赛，真的太厉害了！哈哈，好棒！")
        self.assertTrue(any("排位" in w or "厉害" in w for w in result))
        self.assertTrue(len(result) > 0)

    def test_filters_stopwords(self):
        from src.autoslice.mllm_sdk.audio_analyzer import extract_keywords
        result = extract_keywords("的那个就是在嗯")
        self.assertEqual(result, [])
```

- [ ] **Step 3: Run test**

```bash
PYTHONPATH=.:./src python -m pytest tests/test_autoslice.py::TestKeywordExtraction -v
```

Expected: PASS.

---

### Task 2: Improve Quality Scoring

**Files:**
- Modify: `src/autoslice/mllm_sdk/audio_analyzer.py`
- Modify: `src/autoslice/mllm_sdk/multi_modal_analyzer.py`
- Test: `tests/test_autoslice.py`

**Problem:** `analyze_audio_content` always returns `audio_quality: 0.5`. All slices get the same score, making `slice_quality_filter` useless.

- [ ] **Step 1: Add scoring helpers to `audio_analyzer.py`**

Add these after `detect_emotion`:

```python
_EXCITED_WORDS = re.compile(r"哈哈|好棒|太强了|厉害|牛逼|太好了|开心|666|绝了|好厉害|太牛")
_FILLER_WORDS = re.compile(r"嗯|额|然后|就是|那个|这个|一下|的话|对吧")

def _emotion_density(text: str) -> float:
    if not text:
        return 0.0
    matches = len(_EXCITED_WORDS.findall(text))
    return min(matches / max(len(text) / 10, 1), 1.0)

def _filler_density(text: str) -> float:
    if not text:
        return 0.0
    matches = len(_FILLER_WORDS.findall(text))
    return min(matches / max(len(text) / 10, 1), 1.0)

def _info_density(text: str) -> float:
    clean = re.sub(r"[嗯额的了在着过又很都也还，。！？、,!?]", "", text)
    return len(clean) / max(len(text), 1)
```

- [ ] **Step 2: Update `analyze_audio_content`**

Replace the fixed `audio_quality: 0.5` with computed scoring:

```python
def analyze_audio_content(transcript: str) -> Dict[str, Any]:
    if not transcript or len(transcript) < 10:
        scan_log.warning("Transcript too short for analysis")
        return {
            "audio_theme": "未知",
            "audio_emotion": "neutral",
            "audio_keywords": [],
            "audio_quality": 0.3,
            "audio_highlights": []
        }

    keywords = extract_keywords(transcript)
    emotion = detect_emotion(transcript)

    em_density = _emotion_density(transcript)
    fl_density = _filler_density(transcript)
    inf_density = _info_density(transcript)

    quality = 0.5 + em_density * 0.3 - fl_density * 0.3
    quality = max(0.1, min(1.0, quality))

    if inf_density < 0.3:
        quality = min(quality, 0.4)

    return {
        "audio_theme": "直播内容",
        "audio_emotion": emotion,
        "audio_keywords": keywords,
        "audio_quality": quality,
        "audio_highlights": []
    }
```

- [ ] **Step 3: Update `combine_analysis` in `multi_modal_analyzer.py`**

Change the `retain_recommendation` logic from `quality_score >= 0.5` to:

```python
retain_recommendation = quality_score >= 0.5 and audio_emotion not in ("neutral",) or quality_score >= 0.6
```

More precisely, replace:

```python
retain_recommendation = quality_score >= 0.5
```

with:

```python
retain_recommendation = (
    quality_score >= 0.6
    or (quality_score >= 0.5 and audio_emotion in ("excited", "happy", "angry", "calm"))
)
```

This means: high-quality always passes; borderline passes only if there's detectable emotion; flat neutral at 0.5 gets filtered.

- [ ] **Step 4: Add test**

```python
class TestQualityScoring(unittest.TestCase):
    def test_excited_content_scores_higher(self):
        from src.autoslice.mllm_sdk.audio_analyzer import analyze_audio_content
        high = analyze_audio_content("哈哈好厉害！太强了这波操作！666！牛逼！绝了！")
        low = analyze_audio_content("嗯好的然后就是然后那个就是嗯对")
        self.assertGreater(high["audio_quality"], low["audio_quality"])

    def test_short_transcript_returns_low_quality(self):
        from src.autoslice.mllm_sdk.audio_analyzer import analyze_audio_content
        result = analyze_audio_content("嗯")
        self.assertLessEqual(result["audio_quality"], 0.3)

    def test_filler_heavy_gets_penalized(self):
        from src.autoslice.mllm_sdk.audio_analyzer import analyze_audio_content
        result = analyze_audio_content("嗯额然后就是那个嗯额然后就是那个")
        self.assertLess(result["audio_quality"], 0.5)
```

- [ ] **Step 5: Run test**

```bash
PYTHONPATH=.:./src python -m pytest tests/test_autoslice.py::TestQualityScoring -v
```

Expected: PASS.

---

### Task 3: Improve Title Generation Fallback

**Files:**
- Modify: `src/autoslice/mllm_sdk/multi_modal_analyzer.py`

**Problem:** When keyword extraction fails, `_build_audio_title` falls back to generic "主播直播高能片段".

- [ ] **Step 1: Update `_build_audio_title`**

```python
_FILLER_RE = re.compile(r"^[嗯额的了在着过又很都也还]+$")

def _build_audio_title(artist: str, keywords: list, transcript: str) -> str:
    clean_keywords = []
    for keyword in keywords:
        keyword = re.sub(r"\s+", "", str(keyword))
        if 2 <= len(keyword) <= 6 and keyword not in clean_keywords:
            clean_keywords.append(keyword)

    template = "直播高能" if any(k in transcript for k in ("哈哈", "厉害", "牛逼", "太强", "666")) else "直播片段"

    if clean_keywords:
        title = f"{artist}{template}：{'、'.join(clean_keywords[:2])}"
    elif transcript:
        snippet = re.sub(r"[，。！？、,!?嗯额然后就是那个]", "", transcript)[:12]
        title = f"{artist}{template}：{snippet}" if snippet else f"{artist}{template}"
    else:
        title = f"{artist}精彩片段"

    return _truncate_text(title, 30)
```

Note: add `import re` at the top of the function or ensure it's already imported at module level (it is).

- [ ] **Step 2: Verify manually**

```bash
PYTHONPATH=.:./src python -c "
from src.autoslice.mllm_sdk.multi_modal_analyzer import _build_audio_title
print(_build_audio_title('主播A', ['排位赛', '厉害'], '今天打排位太厉害了'))
print(_build_audio_title('主播A', [], '今天打了一把排位赛真的太厉害了'))
print(_build_audio_title('主播A', [], ''))
"
```

Expected: titles that include meaningful content from transcript when keywords are empty.

---

### Task 4: Cache Whisper Model

**Files:**
- Modify: `src/autoslice/mllm_sdk/audio_analyzer.py`

**Problem:** `transcribe_audio_whisper` calls `whisper.load_model()` on every invocation.

- [ ] **Step 1: Use the existing `_whisper_model` global**

The global `_whisper_model = None` is already declared at module level but never used. Update `transcribe_audio_whisper`:

```python
def transcribe_audio_whisper(audio_path: str, model_size: str = "base") -> Dict[str, Any]:
    try:
        import whisper
    except ImportError:
        scan_log.error("Whisper not installed. Run: pip install openai-whisper")
        return {"transcript": "", "error": "whisper_not_installed"}

    try:
        global _whisper_model
        if _whisper_model is None:
            scan_log.info(f"Loading Whisper model: {model_size}")
            _whisper_model = whisper.load_model(model_size)
        else:
            scan_log.info("Using cached Whisper model")

        scan_log.info(f"Transcribing audio: {audio_path}")
        result = _whisper_model.transcribe(audio_path, language="zh")

        segments = result.get("segments", [])
        for segment in segments:
            if "text" in segment:
                segment["text"] = normalize_transcript(segment["text"])
        transcript = format_transcript_segments(segments, result.get("text", ""))

        scan_log.info(f"Transcription complete: {len(transcript)} chars, {len(segments)} segments")

        return {
            "transcript": transcript,
            "segments": segments,
            "language": result.get("language", "zh")
        }

    except Exception as e:
        scan_log.error(f"Whisper transcription failed: {e}")
        return {"transcript": "", "error": str(e)}
```

- [ ] **Step 2: Add `unload_whisper_model`**

```python
def unload_whisper_model() -> None:
    global _whisper_model
    if _whisper_model is not None:
        del _whisper_model
        _whisper_model = None
    release_gpu_memory()
    scan_log.info("Whisper model unloaded, GPU memory released")
```

---

### Task 5: Fix Temporary Audio Cleanup

**Files:**
- Modify: `src/autoslice/mllm_sdk/audio_analyzer.py`

**Problem:** `cleanup_audio` uses `os.rmdir` which silently fails if directory is non-empty.

- [ ] **Step 1: Replace with `shutil.rmtree`**

```python
import shutil

def cleanup_audio(audio_path: str) -> None:
    if audio_path and os.path.exists(audio_path):
        temp_dir = os.path.dirname(audio_path)
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            scan_log.info("Cleaned up temporary audio directory")
        except OSError:
            pass
```

Remove the `import shutil` if it's not already at the top and add it to the module imports.

---

### Task 6: Dashboard Auto-Refresh

**Files:**
- Modify: `frontend/app.js`

- [ ] **Step 1: Add auto-refresh logic**

Append to `frontend/app.js`, after the existing event listeners:

```javascript
// Auto-refresh every 30s when page is visible
let refreshTimer = setInterval(() => {
  if (document.visibilityState === "visible") {
    refresh();
  }
}, 30000);

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    refresh();
  }
});
```

---

### Task 7: Refined-Slice Marker

**Files:**
- Modify: `src/burn/feedback_refine.py`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`

- [ ] **Step 1: Write `refined: true` in feedback JSON**

In `src/burn/feedback_refine.py`, inside `process_feedback_file`, update the `feedback.update(...)` block to include `"refined": True`:

```python
feedback.update(
    {
        "decision": decision,
        "refined": True,
        "generated_refined_clip": str(refined_clip),
        ...
    }
)
```

- [ ] **Step 2: Show refined badge in Dashboard**

In `frontend/app.js`, update `renderList` to add a badge when `item.refined` is true. The `SliceItem` schema already has `feedback_path`; the feedback data needs to flow into the slice item. Update `file_store.py` `_build_slice_item` to read `refined` from feedback:

In `src/dashboard/file_store.py`, add to `_build_slice_item` after reading feedback:

```python
item.refined = feedback.get("refined", False)
```

Add `refined: bool = False` to `SliceItem` in `schemas.py`.

In `frontend/app.js`, update `renderList`:

```javascript
const badge = item.refined ? ' <span class="refined-badge">已精切</span>' : '';
button.querySelector(".slice-name").innerHTML = `${item.name}${badge}`;
```

- [ ] **Step 3: Add style**

In `frontend/styles.css`:

```css
.refined-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 3px;
  background: #e0f2e9;
  color: #1a7f37;
  font-size: 11px;
  font-weight: 600;
}
```

- [ ] **Step 4: Update test**

Update `tests/test_feedback_refine.py` — the `test_process_feedback_file_refines_keep_manual_range_and_queues` test already reads back the feedback JSON. Assert that `feedback_data["refined"] is True`.

---

## Final Verification

```bash
source venv/bin/activate

# Unit tests
PYTHONPATH=.:./src python -m pytest tests/test_autoslice.py tests/test_feedback_refine.py tests/test_dashboard_api.py tests/test_dashboard_frontend.py -v

# Manual keyword extraction check
python -c "
from src.autoslice.mllm_sdk.audio_analyzer import extract_keywords
print(extract_keywords('今天打了一把排位赛，真的太厉害了！哈哈，好棒！'))
"

# Manual quality scoring check
python -c "
from src.autoslice.mllm_sdk.audio_analyzer import analyze_audio_content
print(analyze_audio_content('哈哈好厉害！太强了这波操作！666！'))
print(analyze_audio_content('嗯好的然后就是然后那个就是嗯对'))
"

# Shell syntax
bash -n slice.sh && bash -n refine_feedback.sh && bash -n start_dashboard.sh

# Git check
git diff --check
```
