from pathlib import Path
import json

from .domain import analyze, explore, household_timeline, validate
from .storage import Store, fingerprint


class Workbench:
    def __init__(self, root, state):
        self.root = Path(root)
        self.product = json.loads((self.root / "product.json").read_text(encoding="utf-8"))
        self.store = Store(Path(state) / "research.sqlite3")
        initial = json.loads((self.root / "fixtures" / "data.json").read_text(encoding="utf-8"))
        validate(initial)
        self.default_revision = self.store.put_dataset("演示材料", initial)

    def context(self):
        return {"product": self.product, "default_revision": self.default_revision,
                "datasets": self.store.datasets(), "notebooks": self.store.notebooks()}

    def upload(self, body):
        data = body["data"]
        try:
            validate(data)
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("字段结构不完整或类型不符") from error
        return {"revision": self.store.put_dataset(body.get("label", ""), data)}

    def _checked(self, body):
        revision = body.get("revision", self.default_revision)
        selection = body.get("selection", self.product["selection"])
        if not isinstance(selection, dict):
            raise ValueError("选择条件必须是对象")
        return revision, selection

    def inspect(self, body):
        revision, selection = self._checked(body)
        data = self.store.dataset(revision)
        result = explore(data, selection)
        return {"revision": revision, "selection": selection, "data_sha256": fingerprint(data), "view": result}

    def analyze(self, body):
        revision, selection = self._checked(body)
        caliber = body.get("caliber", self.product.get("caliber"))
        data = self.store.dataset(revision)
        result = analyze(data, selection, caliber)
        return {"revision": revision, "selection": selection, "caliber": result["caliber"],
                "data_sha256": fingerprint(data), "analysis": result}

    def household(self, revision, household):
        revision = revision or self.default_revision
        if not household:
            raise ValueError("请指定家庭编号")
        data = self.store.dataset(revision)
        return {"revision": revision, "timeline": household_timeline(data, household)}

    def save(self, body):
        result = self.inspect(body)
        if body.get("caliber") is not None:
            analysis = self.analyze(body)
            result["caliber"] = analysis["caliber"]
            result["analysis"] = analysis["analysis"]
        return self.store.save(body.get("title", ""), result["revision"], result["selection"], result)
