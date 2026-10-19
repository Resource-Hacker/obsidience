# Embedded Harness2 package

Base: Google Research `harness2` commit
`1cfe254e8d25b15f37048c3730134686abe60335`, Apache-2.0.

`0001-embedded-python314.patch` changes package metadata to
`0.1.0+obsidience.1`, admits Python 3.14, includes `obsidience-build.json`, and
disables implicit `.env` loading when the embedding application imports the
package. It does not alter the refinement algorithm. The manifest is generated
from the patched source and verified in both the built wheel and runtime
admission; it is not a self-asserted version label.

Reproduce with `python3 obsidience/scripts/install-optimization --build-only`.
The installer verifies the fixed archive SHA256 before extraction and patching.
Update the artifact lock and backend manifest pin together when changing this
patch or upstream revision. Review the affected embedded paths on the current
Python version; the local compatibility decision does not cover unused upstream
benchmark installers or provider CLIs.

The upstream deterministic demo passed both recursion modes on Python 3.14.7
from the built wheel. See `docs/harness2.md` for integration scope, retained
AutoSaddler behavior, upstream discussions and rollback.
