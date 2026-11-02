# Reads one Base64-encoded UTF-8 phrase per line from stdin and speaks it.
# Base64 keeps the pipe pure ASCII, so the Chinese text never depends on the
# console code page.  Runs as a persistent helper so the GUI never blocks on TTS.
$ErrorActionPreference = 'Stop'
$synth = $null
try {
    Add-Type -AssemblyName System.Speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $zh = $synth.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'zh*' } | Select-Object -First 1
    if ($zh) { $synth.SelectVoice($zh.VoiceInfo.Name) }
    while ($null -ne ($line = [Console]::ReadLine())) {
        try {
            if (-not $zh) { throw 'No Chinese voice' }
            $text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($line))
            $synth.Speak($text)
            [Console]::WriteLine('OK')
        } catch {
            [Console]::WriteLine('FALLBACK')
        }
    }
} finally {
    if ($synth) { $synth.Dispose() }
}
