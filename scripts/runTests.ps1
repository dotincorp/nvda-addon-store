# Run the addon's unit tests using NVDA's bundled Python interpreter.
#
# This is what the CI workflow runs (.github/workflows/ci.yaml -> Run unittests).
# Running it locally before push catches the same regressions CI does — much
# faster than waiting for the GitHub Actions matrix to fail.
#
# Requires: an NVDA source checkout at ../nvda with a populated .venv. The
# default NVDA bootstrap (`scons source` or the equivalent uv-driven flow)
# leaves you with that.
#
# Usage:
#   pwsh scripts/runTests.ps1                     # run the full suite
#   pwsh scripts/runTests.ps1 tests.test_foo      # run one test module
#
# The PYTHONPATH wires in NVDA's source tree (so `import braille`, `import
# louis`, etc. resolve) plus its miscDeps/python (vendor-bundled libs).

param(
	[Parameter(ValueFromRemainingArguments = $true)]
	[string[]] $Args
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$nvdaRoot = Resolve-Path (Join-Path $repoRoot "..\nvda")
$python = Join-Path $nvdaRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
	throw "NVDA's venv python not found at $python — run NVDA's bootstrap first."
}

$env:PYTHONPATH = (Join-Path $nvdaRoot "source") + ";" + (Join-Path $nvdaRoot "miscDeps\python")

Push-Location $repoRoot
try {
	if ($Args.Count -eq 0) {
		& $python -m unittest discover -s tests -t .
	} else {
		& $python -m unittest @Args
	}
	exit $LASTEXITCODE
} finally {
	Pop-Location
}
