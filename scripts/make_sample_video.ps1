# Generates samples\speech_sample.mp4: synthetic video + Windows text-to-speech narration.
# Purely local; useful for testing transcription/editing without a real recording.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$ffmpeg = Join-Path $root "tools\ffmpeg\ffmpeg.exe"
$out = Join-Path $root "samples"
New-Item -ItemType Directory -Force $out | Out-Null

$text = @"
Welcome to today's discussion. Today we are going to talk about business automation.
Many small businesses waste hours every week on repetitive tasks like invoicing and scheduling.
Here is the first big idea. Automate anything you do more than three times a week.
Um, so, let me think about that for a second.
The second idea is to start small. Pick one process, automate it, and measure the time you save.
Most people try to automate everything at once, and that is why they fail.
The third idea is the most important. Always keep a human in the loop for decisions that affect customers.
Automation should give you more time, not remove your judgment.
So to summarize, automate the boring work, start small, and keep people in charge.
Thanks for watching, and I will see you in the next video.
"@

Add-Type -AssemblyName System.Speech
$wav = Join-Path $out "speech.wav"
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = 0
$synth.SetOutputToWaveFile($wav)
$synth.Speak($text)
$synth.Dispose()

$mp4 = Join-Path $out "speech_sample.mp4"
& $ffmpeg -y -loglevel error -f lavfi -i "testsrc2=size=1280x720:rate=30" -i $wav `
  -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac $mp4
Remove-Item $wav
Write-Output $mp4
