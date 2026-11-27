"""The plain-English lines Gemini writes must turn into the right robot actions."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import autovideo as av

hints = ["Upload photo", "Send", "Sign up"]
def acts(line): return av.parse_actions(line, hints)
assert acts("Upload a photo") == [{"upload": ["Upload photo", ""]}], acts("Upload a photo")
assert acts("Upload your own image")[0]["upload"][0] == "Upload photo"
assert acts("Type the temp email in the Email box") == [{"type": ["Email", "{email}"]}], acts("Type the temp email in the Email box")
assert acts("Enter a password") == [{"type": ["Password", "{password}"]}]
assert acts("Enter the verification code") == [{"type": ["Code", "{code}"]}]
assert acts("Open the confirmation link") == [{"verify": "link"}]
assert acts("Check the temp inbox") == [{"verify": "link"}]
assert acts('Type "how are you" in the Type your message box, then click Send') == [{"type": ["Type your message", "how are you"]}, {"click": "Send"}]
# exact tags still win
a, _ = av.parse_tags("[upload Upload photo | 2] [type Email | {email}] [verify]")
assert a == [{"upload": ["Upload photo", "2"]}, {"type": ["Email", "{email}"]}, {"verify": "link"}], a
# script meta lines
plan = av.plan_builtin("Video: x\nLanguage: Bangla\nTemplate: neon\nDepth: 3\nOutputs: vertical, instagram\nCaptions: box\nOpen https://a.com || Hi.\n|| Bye.", {})
assert plan["voice"].startswith("bn-BD") and plan["meta"] == {"template": "neon", "depth": "3", "outputs": "vertical, instagram", "captions": "box"}, plan
print("parse tests OK")
