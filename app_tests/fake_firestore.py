"""
Minimal in-memory fake mimicking the small slice of the Firestore client
API this app actually uses (collection/document/get/set/update/where/
order_by/limit/stream). Lets CI run real request/response tests against
app.py without needing live Firebase credentials in GitHub Actions.
"""
import itertools
import operator

_id_counter = itertools.count(1)

_OPS = {
    "==": operator.eq,
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
}


class FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = dict(data) if data is not None else None

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class FakeDocRef:
    def __init__(self, store, collection, doc_id):
        self._store = store
        self._collection = collection
        self.id = doc_id

    def set(self, data, merge=False):
        bucket = self._store.setdefault(self._collection, {})
        if merge and self.id in bucket:
            bucket[self.id].update(data)
        else:
            bucket[self.id] = dict(data)

    def update(self, data):
        bucket = self._store.setdefault(self._collection, {})
        if self.id not in bucket:
            raise KeyError(f"No document {self.id} to update")
        bucket[self.id].update(data)

    def get(self):
        bucket = self._store.get(self._collection, {})
        return FakeSnapshot(self.id, bucket.get(self.id))


class FakeQuery:
    def __init__(self, store, collection, filters=None, order=None, limit_n=None):
        self._store = store
        self._collection = collection
        self._filters = filters or []
        self._order = order
        self._limit = limit_n

    def where(self, field, op, value):
        return FakeQuery(
            self._store, self._collection,
            self._filters + [(field, op, value)], self._order, self._limit,
        )

    def order_by(self, field, direction="ASCENDING"):
        return FakeQuery(self._store, self._collection, self._filters, (field, direction), self._limit)

    def limit(self, n):
        return FakeQuery(self._store, self._collection, self._filters, self._order, n)

    def stream(self):
        bucket = self._store.get(self._collection, {})
        docs = []
        for doc_id, data in bucket.items():
            if data is None:
                continue
            ok = True
            for field, op, value in self._filters:
                actual = data.get(field)
                if actual is None or not _OPS[op](actual, value):
                    ok = False
                    break
            if ok:
                docs.append(FakeSnapshot(doc_id, data))
        if self._order:
            field, direction = self._order
            docs.sort(key=lambda s: s.to_dict().get(field), reverse=(direction == "DESCENDING"))
        if self._limit:
            docs = docs[: self._limit]
        return docs


class FakeCollectionRef(FakeQuery):
    def __init__(self, store, collection):
        super().__init__(store, collection)

    def document(self, doc_id=None):
        if doc_id is None:
            doc_id = f"auto-{next(_id_counter)}"
        return FakeDocRef(self._store, self._collection, doc_id)


class FakeFirestoreClient:
    def __init__(self):
        self._store = {}

    def collection(self, name):
        return FakeCollectionRef(self._store, name)