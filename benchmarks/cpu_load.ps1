# Report current CPU load, and the eight processes using the most CPU time.
#
# ab_bench.py's absolute numbers are only meaningful on a quiet machine: it
# measures wall-clock time of short runs, so anything else competing for cores
# inflates both sides unevenly and turns a 2% difference into noise.  (The A/B
# *ratio* is more robust -- runs are interleaved and the order alternates --
# but a heavily loaded machine still widens the error bars past the effect
# size we usually care about.)
#
# Historically, valid A/B runs here were taken at 25-30% load.  Above ~50%,
# wait rather than measure, and use the process list to see what to wait for.
#
#     powershell -File benchmarks/cpu_load.ps1
#
$avg = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
Write-Output "cpu_load_percent=$avg"
Get-Process | Sort-Object CPU -Descending | Select-Object -First 8 Name, Id, CPU | Format-Table -AutoSize
