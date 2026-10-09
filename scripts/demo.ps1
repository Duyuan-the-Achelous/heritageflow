param(
    [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

function Headers([string]$Tenant, [string]$Role = "visitor") {
    return @{ Authorization = "Bearer demo:$Tenant`:$Role" }
}

function Invoke-JsonPost([string]$Uri, [hashtable]$RequestHeaders, [hashtable]$Body) {
    return Invoke-RestMethod -Method Post -Uri "$BaseUrl$Uri" -Headers $RequestHeaders `
        -ContentType "application/json" -Body ($Body | ConvertTo-Json)
}

Write-Host "1/7 Checking readiness"
Invoke-RestMethod -Uri "$BaseUrl/health" | ConvertTo-Json

Write-Host "2/7 Creating a Guanlin capacity slot"
$slot = Invoke-JsonPost "/v1/admin/slots" (Headers "guanlin" "tenant_admin") @{
    attraction_id = "guanlin-main"
    starts_at = "2035-07-01T09:00:00Z"
    ends_at = "2035-07-01T10:00:00Z"
    capacity = 5
}
$slot | ConvertTo-Json

Write-Host "3/7 Creating a reservation"
$reservationHeaders = Headers "guanlin"
$reservationHeaders["Idempotency-Key"] = "demo-$($slot.id)"
$reservationBody = @{
    attraction_id = "guanlin-main"
    slot_id = $slot.id
    visitor_reference = "synthetic-demo-visitor"
    quantity = 1
}
$reservation = Invoke-JsonPost "/v1/reservations" $reservationHeaders $reservationBody
$reservation | ConvertTo-Json

Write-Host "4/7 Replaying the same idempotent request"
$replay = Invoke-JsonPost "/v1/reservations" $reservationHeaders $reservationBody
if ($replay.id -ne $reservation.id) { throw "Idempotent replay returned a different reservation" }
Write-Host "Same reservation returned: $($replay.id)"

Write-Host "5/7 Confirming a foreign tenant cannot read it"
try {
    Invoke-RestMethod -Uri "$BaseUrl/v1/reservations/$($reservation.id)" -Headers (Headers "tomb-museum")
    throw "Cross-tenant read unexpectedly succeeded"
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
    Write-Host "Cross-tenant read returned 404 as expected"
}

Write-Host "6/7 Validating admission once"
$validated = Invoke-JsonPost "/v1/validations" (Headers "guanlin" "validator") @{
    validation_code = $reservation.validation_code
}
$validated | ConvertTo-Json
try {
    Invoke-JsonPost "/v1/validations" (Headers "guanlin" "validator") @{
        validation_code = $reservation.validation_code
    }
    throw "A validation code was accepted twice"
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 409) { throw }
    Write-Host "Second validation returned 409 as expected"
}

Write-Host "7/7 Reading tenant metrics"
Invoke-RestMethod -Uri "$BaseUrl/v1/admin/metrics" -Headers (Headers "guanlin" "tenant_admin") |
    ConvertTo-Json
Write-Host "HeritageFlow local demo passed"
