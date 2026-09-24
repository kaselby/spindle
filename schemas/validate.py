#!/usr/bin/env -S uv run --quiet --with jsonschema --with referencing python3
"""Load every *.schema.json here, check it is valid draft 2020-12, and run
the sample instances below (expected valid / invalid). Run: ./validate.py
(needs uv) or python3 validate.py with jsonschema + referencing installed."""
import json, glob, os, sys
import jsonschema
from referencing import Registry, Resource

here = os.path.dirname(os.path.abspath(__file__))
schemas = {}
for f in sorted(glob.glob(os.path.join(here, "*.schema.json"))):
    s = json.load(open(f)); schemas[os.path.basename(f)] = s
    jsonschema.Draft202012Validator.check_schema(s)
    print("ok schema:", os.path.basename(f))
reg = Registry().with_resources(
    [(n, Resource.from_contents(s)) for n, s in schemas.items()]
    + [(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
V = lambda n: jsonschema.Draft202012Validator(schemas[n], registry=reg)

TS = "2026-09-11T11:10:00-04:00"
ident = {"session": "tr-abc123", "agent": "worker"}
# Event ids are timestamp+random strings and checkpoint ids are cNNNN
# the earlier integer/digit forms are now invalid.
E1, E2, E3, E4, E5, E6, E7 = (f"20260911T1110{n:02d}-7kmq" for n in range(1, 8))
cases = {
 "origin.schema.json": [
  ({"thread":"k7q2m9xa","title":"Thread schemas","created":TS,"by":ident}, True),
  ({"thread":"k7q2m9xa","created":TS,"by":ident}, False)],
 "tasks.schema.json": [
  ({"tasks":[{"id":"t9k2a","text":"write schemas","done":False},{"text":"hand-added"}]}, True),
  ({"tasks":[{"id":"bad","text":"x"}]}, False)],
 "event.schema.json": [
  ({"id":E1,"ts":TS,"by":ident,"type":"created","payload":{"title":"x"}}, True),
  ({"id":E2,"ts":TS,"by":ident,"type":"claim","payload":{"intent":"drafting"}}, True),
  ({"id":E2,"ts":TS,"by":ident,"type":"claim"}, True),
  ({"id":E7,"ts":TS,"by":ident,"type":"state-changed","payload":{"from":"inactive","to":"open"}}, True),
  ({"id":E3,"ts":TS,"by":ident,"type":"checkpoint","payload":{"checkpoint":"c0001","at":E2,"headline":"h"}}, True),
  ({"id":E4,"ts":TS,"by":ident,"type":"register","payload":{"checkpoint":"c0001","registration":{"path":"docs/a.md","kind":"guide","purpose":"p"}}}, False),
  ({"id":E4,"ts":TS,"by":ident,"type":"register","payload":{"checkpoint":"c0001","registration":{"path":"docs/a.md","kind":"guide","purpose":"p","read-when":"r"}}}, True),
  ({"id":E5,"ts":TS,"by":{"agent":"worker"},"type":"note","payload":{"text":"x"}}, False),
  ({"id":E6,"ts":TS,"by":ident,"type":"bogus","payload":{}}, False),
  ({"id":1,"ts":TS,"by":ident,"type":"note","payload":{"text":"x"}}, False),
  ({"id":E6,"ts":TS,"by":ident,"type":"child-landed","payload":{"child":"k7q2m9xa"}}, False),
  # Lifecycle events.
  ({"id":E6,"ts":TS,"by":ident,"type":"child-merged","payload":{"child":"k7q2m9xa","checkpoint":"c0003",
    "promoted":["docs/a.md"],"pointers":["artifacts/b.csv"],"tasks":["t9k2a"],"forced":False}}, True),
  ({"id":E6,"ts":TS,"by":ident,"type":"child-merged","payload":{"child":"k7q2m9xa"}}, False),
  ({"id":E6,"ts":TS,"by":ident,"type":"merged-into","payload":{"parent":"k7q2m9xa","checkpoint":"c0007"}}, True),
  ({"id":E6,"ts":TS,"by":ident,"type":"merged-into","payload":{"parent":"k7q2m9xa","checkpoint":"7"}}, False),
  ({"id":E6,"ts":TS,"by":ident,"type":"child-closed","payload":{"child":"k7q2m9xa","checkpoint":"c0002"}}, True),
  ({"id":E6,"ts":TS,"by":ident,"type":"child-reopened","payload":{"child":"k7q2m9xa"}}, True),
  ({"id":E6,"ts":TS,"by":ident,"type":"child-superseded","payload":{"child":"k7q2m9xa","successor":"m3n4p5"}}, True),
  ({"id":E6,"ts":TS,"by":ident,"type":"child-adopted","payload":{"child":"k7q2m9xa","title":"t","from":"m3n4p5"}}, True),
  ({"id":E6,"ts":TS,"by":ident,"type":"reparented","payload":{"from":"k7q2m9xa","to":"m3n4p5"}}, True),
  ({"id":E6,"ts":TS,"by":ident,"type":"reparented","payload":{"from":"k7q2m9xa"}}, False),
  ({"id":E6,"ts":TS,"by":ident,"type":"reopened","payload":{}}, True),
  ({"id":E6,"ts":TS,"by":ident,"type":"origin-replaced","payload":{"previous":"origin-1.md","after-checkpoint":"c0007","title":"New anchor"}}, True),
  ({"id":E6,"ts":TS,"by":ident,"type":"origin-replaced","payload":{"previous":"origin.md","after-checkpoint":"c0007"}}, False),
  ({"id":E6,"ts":TS,"by":ident,"type":"linked","payload":{"kind":"blocked-by","target":"m3n4p5"}}, True),
  ({"id":E6,"ts":TS,"by":ident,"type":"unlinked","payload":{"kind":"follows","target":"m3n4p5"}}, False),
  ({"id":E7,"ts":TS,"by":ident,"type":"state-changed","payload":{"from":"open","to":"superseded","reason":"superseded","successor":"m3n4p5"}}, True),
  ({"id":E7,"ts":TS,"by":ident,"type":"state-changed","payload":{"from":"inactive","to":"active"}}, True),
  ({"id":E7,"ts":TS,"by":ident,"type":"state-changed","payload":{"from":"active","to":"dropped"}}, True),
  ({"id":E7,"ts":TS,"by":ident,"type":"state-changed","payload":{"from":"active","to":"finished"}}, False),
  ({"id":E6,"ts":TS,"by":ident,"type":"child-dropped","payload":{"child":"k7q2m9xa","checkpoint":"c0002"}}, True),
  ({"id":E4,"ts":TS,"by":ident,"type":"register","payload":{"checkpoint":"c0001","from":"k7q2m9xa@c0003",
    "registration":{"path":"docs/a.md","kind":"guide","purpose":"p","read-when":"r"}}}, True),
  ({"id":E4,"ts":TS,"by":ident,"type":"register","payload":{"checkpoint":"c0001","pointer":"k7q2m9xa:artifacts/b.csv@c0003",
    "registration":{"path":"artifacts/b.csv","kind":"dataset","purpose":"p"}}}, True),
  ({"id":E4,"ts":TS,"by":ident,"type":"register","payload":{"checkpoint":"c0001","pointer":"artifacts/b.csv",
    "registration":{"path":"artifacts/b.csv","kind":"dataset","purpose":"p"}}}, False),
  ({"id":E1,"ts":TS,"by":ident,"type":"task-added","payload":{"task":"t9k2a","text":"x","from":"k7q2m9xa"}}, True)],
 "checkpoint.schema.json": [
  ({"id":"c0001","thread":"k7q2m9xa","at":E2,"ts":TS,"by":ident,"headline":"h"}, True),
  ({"id":"c0001","thread":"k7q2m9xa","at":E2,"ts":TS,"by":ident,"headline":"h"*121}, False),
  ({"id":"0001","thread":"k7q2m9xa","at":E2,"ts":TS,"by":ident,"headline":"h"}, False),
  ({"id":"c0001","thread":"k7q2m9xa","at":E2,"ts":TS,"by":ident,"headline":"h","forced-by":"merge"}, True),
  ({"id":"c0001","thread":"k7q2m9xa","at":E2,"ts":TS,"by":ident,"headline":"h","forced-by":"unsynced-bound"}, False),
  ({"id":"c0005","thread":"k7q2m9xa","at":E4,"ts":TS,"by":ident,"headline":"h","inherited":[{"since":"c0002","text":"x"}]*3}, True),
  ({"id":"c0005","thread":"k7q2m9xa","at":E4,"ts":TS,"by":ident,"headline":"h","inherited":[{"since":"c0002","text":"x"}]*4}, False),
  # The checkpoint no longer carries the sha of its own commit.
  ({"id":"c0001","thread":"k7q2m9xa","at":E2,"ts":TS,"by":ident,"headline":"h","commit":"a"*40}, False)],
 "thread.schema.json": [
  ({"id":"k7q2m9xa","slug":"thread-schemas","title":"T","state":"active","created":TS,"last-event":TS,
    "tip":E3,"events-since-checkpoint":0,"children":[],
    "claims":[{"by":ident,"intent":"i","since":TS,"last-seen":TS}]}, True),
  ({"id":"k7q2m9xa","slug":"thread-schemas","title":"T","state":"inactive","created":TS,"last-event":TS,
    "tip":E3,"events-since-checkpoint":0,"children":[],"claims":[]}, True),
  ({"id":"k7q2m9xa","slug":"thread-schemas","title":"T","state":"active","created":TS,"last-event":TS,
    "tip":E3,"events-since-checkpoint":0,"claims":[],
    "children":[{"id":"m3n4p5","title":"C","state":"merged","merged":"c0003"}]}, True),
  ({"id":"k7q2m9xa","slug":"thread-schemas","title":"T","state":"active","created":TS,"last-event":TS,
    "tip":E3,"events-since-checkpoint":0,"claims":[],
    "children":[{"id":"m3n4p5","title":"C","state":"merged","landed":True}]}, False),
  ({"id":"k7q2m9xa","slug":"thread-schemas","title":"T","state":"archived","created":TS,"last-event":TS,
    "tip":E3,"events-since-checkpoint":0,"children":[],"claims":[]}, False)],
}
fails = 0
for name, cs in cases.items():
    v = V(name)
    for inst, expect in cs:
        errs = list(v.iter_errors(inst)); ok = not errs
        good = ok == expect; fails += not good
        print(f"{'PASS' if good else 'FAIL'} {name} expect_valid={expect} got_valid={ok}"
              + ("" if good else " :: " + "; ".join(e.message[:90] for e in errs)))
print("failures:", fails)
sys.exit(1 if fails else 0)
