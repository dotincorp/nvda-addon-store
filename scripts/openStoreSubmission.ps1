# Open the NVDA add-on store registration form, prefilled for a release.
#
# The datastore's intake fires on an issue label that only the web form applies,
# so the submission cannot be automated end to end. This gets everything that
# can be prefilled into the form and opens it in the default browser.
#
# Usage:
#   pwsh scripts/openStoreSubmission.ps1 -Version 0.9.93 -Channel dev
#   pwsh scripts/openStoreSubmission.ps1 -Version 1.0.0 -Channel stable -WhatIf
#
# Channel cannot be prefilled — see the note printed at the end.

[CmdletBinding(SupportsShouldProcess = $true)]
param(
	[Parameter(Mandatory = $true)]
	[string] $Version,

	[Parameter(Mandatory = $true)]
	[ValidateSet('stable', 'beta', 'dev')]
	[string] $Channel,

	[string] $Repo = 'dotincorp/nvda-addon-store',

	[string] $Publisher = 'Dot Incorporated'
)

$ErrorActionPreference = 'Stop'

# Read the asset URL off the release rather than composing it, so a renamed
# asset or a tag that is not the bare version fails here instead of producing a
# submission that 404s during validation.
$downloadUrl = gh release view $Version --repo $Repo --json assets `
	-q '.assets[] | select(.name | endswith(".nvda-addon")) | .url'

if ($LASTEXITCODE -ne 0) {
	throw "Could not read release '$Version' from $Repo."
}
if (-not $downloadUrl) {
	throw "Release '$Version' has no .nvda-addon asset. Did the release workflow finish?"
}
if ($downloadUrl -is [array] -or $downloadUrl -match "`n") {
	throw "Release '$Version' has more than one .nvda-addon asset:`n$downloadUrl"
}

$sourceUrl = "https://github.com/$Repo/"

# The title parameter replaces the template's default entirely, so it has to
# carry the "[Submit add-on]: " prefix itself.
$fields = [ordered]@{
	'title'        = "[Submit add-on]: dotPad $Version"
	'download-url' = $downloadUrl
	'source-url'   = $sourceUrl
	'publisher'    = $Publisher
	'license-name' = 'GPL v2'
	'license-url'  = 'https://www.gnu.org/licenses/gpl-2.0.html'
}

$query = ($fields.GetEnumerator() | ForEach-Object {
		'{0}={1}' -f $_.Key, [uri]::EscapeDataString($_.Value)
	}) -join '&'

# template= is what applies the autoSubmissionFromIssue label; never pass
# labels= by hand.
$url = "https://github.com/nvaccess/addon-datastore/issues/new?template=registerAddon.yml&$query"

if ($PSCmdlet.ShouldProcess($url, 'Open in default browser')) {
	Start-Process $url
}

Write-Host ''
Write-Host "Add-on:   dotPad $Version"
Write-Host "Download: $downloadUrl"
Write-Host ''
Write-Host "ACTION REQUIRED: set Channel to '$Channel' by hand." -ForegroundColor Yellow
Write-Host "GitHub's issue form ignores query-parameter prefills for dropdowns" -ForegroundColor Yellow
Write-Host "(verified: neither the option text nor its index selects anything)," -ForegroundColor Yellow
Write-Host 'so Channel is the one field that arrives empty.' -ForegroundColor Yellow
