# Music Studio MCP for ACE-Step

[English](README.md) · **Italiano**

Nome tecnico: `music-studio-mcp-for-ace-step` · Versione **1.0.0**

Un server [MCP](https://modelcontextprotocol.io) che permette a un agente AI di creare musica con ACE-Step 1.5 sul tuo
PC. Descrivi il brano in chat; l'agente ti fa qualche domanda (stile, voce, lingua, durata indicativa, loop…), scrive
i tag di stile e il testo, ti mostra un riepilogo e, dopo il tuo OK, genera il brano tramite l'app
**Music Studio for ACE-Step**.

## Agenti supportati

| Agente | Stato |
|---|---|
| Claude Code | **verificato** |
| Codex (CLI, estensione IDE, app desktop) | **verificato** |
| Claude Desktop, Gemini CLI, Qwen Code, GitHub Copilot CLI, VS Code (Copilot Chat), Cline, Roo Code, Kilo Code, Cursor, Windsurf, Kiro, Amazon Q Developer, LM Studio, opencode, Continue, Antigravity, Zed | non verificati — configurati con il formato documentato da ciascun agente, dovrebbero funzionare |

Qualsiasi altro agente che supporta i server MCP su stdio funziona con la configurazione generica (vedi
*Installazione manuale*).

## Requisiti

- **Music Studio for ACE-Step aperta** mentre usi l'agente, con `"enable_api": true` nel suo `config.json`
  (è il predefinito). Attendi che la pagina di ACE-Step sia visibile.
- [uv](https://docs.astral.sh/uv/) (serve già ad ACE-Step). Il server è l'unico file `mcp/music_studio_mcp.py`; uv
  scarica la sua sola dipendenza (`mcp`) la prima volta.
- ffmpeg per i loop senza stacchi (`winget install Gyan.FFmpeg`; serve comunque ad ACE-Step).

## Installazione (automatica)

Apri un terminale nella cartella dell'app (quella con `Music Studio.exe`, oppure la radice del repository) ed esegui:

```powershell
uv run mcp\install.py
```

L'installer trova gli agenti AI installati sul PC — app desktop, strumenti da riga di comando ed estensioni di VS Code
— mostra dove ognuno salva i suoi server MCP e chiede quali configurare (Invio = tutti). Ogni file viene copiato
(`<file>.bak-<data>`) prima di essere modificato. Poi **riavvia gli agenti**.

| Opzione | Effetto |
|---|---|
| `--list` | mostra solo gli agenti trovati e i loro file di configurazione |
| `--all` | configura tutti gli agenti trovati senza chiedere |
| `--dry-run` | mostra cosa cambierebbe, senza modificare nulla |
| `--uninstall` | rimuove il server dagli agenti |
| `--print` | stampa la configurazione per qualsiasi altro agente |

Dove scrive:

| Agente | File |
|---|---|
| Claude Code | `claude mcp add --scope user` (oppure `~/.claude.json`) |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` (+ la copia della versione Microsoft Store in `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\`) |
| Codex | `~/.codex/config.toml` |
| Gemini CLI / Qwen Code | `~/.gemini/settings.json` / `~/.qwen/settings.json` |
| Antigravity | `~/.gemini/antigravity/mcp_config.json` |
| GitHub Copilot CLI | `~/.copilot/mcp-config.json` |
| VS Code (Copilot Chat) | `%APPDATA%\Code\User\mcp.json` (anche *Code - Insiders*) |
| Cline / Roo Code / Kilo Code | il loro file `settings` dentro `globalStorage` di VS Code |
| Cursor / Windsurf | `~/.cursor/mcp.json` / `~/.codeium/windsurf/mcp_config.json` |
| Kiro / Amazon Q Developer | `~/.kiro/settings/mcp.json` / `~/.aws/amazonq/mcp.json` |
| LM Studio | `~/.lmstudio/mcp.json` |
| opencode | `~/.config/opencode/opencode.json` |
| Continue | `~/.continue/config.yaml` |
| Zed | `%APPDATA%\Zed\settings.json` (di solito contiene commenti: l'installer non lo tocca, aggiungilo a mano) |

## Installazione (manuale)

Sostituisci `C:\percorso\Music Studio` con la tua cartella. Se l'agente non trova `uv`, usa il percorso completo
(`where uv` lo mostra, di solito `C:\Users\<tuo-utente>\.local\bin\uv.exe`).

**Claude Code**

```powershell
claude mcp add --scope user music-studio-mcp-for-ace-step -- uv run --script "C:\percorso\Music Studio\mcp\music_studio_mcp.py"
```

**Codex** — `~/.codex/config.toml`:

```toml
[mcp_servers.music-studio-mcp-for-ace-step]
command = 'uv'
args = ['run', '--script', 'C:\percorso\Music Studio\mcp\music_studio_mcp.py']
startup_timeout_sec = 120
tool_timeout_sec = 120
```

**La maggior parte degli altri agenti** (Claude Desktop, Gemini CLI, Cursor, Windsurf, Cline, Kiro, LM Studio, …) — nel
loro file `mcpServers`:

```json
{
  "mcpServers": {
    "music-studio-mcp-for-ace-step": {
      "command": "uv",
      "args": ["run", "--script", "C:\\percorso\\Music Studio\\mcp\\music_studio_mcp.py"]
    }
  }
}
```

VS Code usa `"servers"` con `"type": "stdio"`; GitHub Copilot CLI usa `"type": "local"` e `"tools": ["*"]`; Zed usa
`"context_servers"` con `"source": "custom"`. `uv run mcp\install.py --print` stampa il comando esatto.

## Come si usa

1. Apri Music Studio for ACE-Step e attendi la pagina di ACE-Step.
2. Chiedi all'agente, ad esempio:
   - *"Fammi un brano lo-fi rilassante di 1 minuto per studiare"*
   - *"Scrivi e genera una canzone pop italiana sull'estate, voce femminile, circa 2 minuti"*
   - *"Musica di sottofondo per un livello di un platform, chiptune, deve andare in loop all'infinito"*
3. L'agente controlla ACE-Step, poi chiede ciò che manca:
   - stile, atmosfera e strumenti;
   - voce e lingua;
   - **durata indicativa con il massimo tra parentesi** (es. *"Durata? (max 8 min)"*), oppure lasci scegliere ACE-Step;
   - **loop senza stacchi** (facoltativo);
   - tempo e tonalità;
   - numero di versioni.

   I client che supportano i moduli MCP mostrano un modulo; gli altri fanno le domande in chat.
4. Mostra una tabella di riepilogo; dopo il tuo OK genera (un brano di 30–60 s richiede circa un minuto) e ti dice
   dove si trova il file: la cartella `gradio_outputs\mcp_<data>_<ora>\` di ACE-Step (*Apri cartella dei brani
   generati* nel menu dell'app).

Alcuni client offrono anche il prompt pronto **compose_song** (in Claude Code: `/mcp__music-studio-mcp-for-ace-step__compose_song`).

### Testi e lingue

Puoi parlare con l'agente in qualsiasi lingua. ACE-Step capisce meglio lo stile musicale descritto con tag in inglese,
quindi l'agente traduce la tua descrizione in tag inglesi; il **testo** della canzone resta nella lingua che scegli per
la voce (italiano, spagnolo, giapponese, …). Per il testo puoi scegliere:

- **lo scrive l'agente** partendo dall'argomento;
- **lo fornisci tu**: incolla il tuo testo — l'agente usa le tue parole così come sono e aggiunge solo i tag delle
  sezioni se mancano;
- **lo improvvisa ACE-Step** (il suo modello linguistico scrive tag, testo e durata).

Nei testi di ACE-Step le sezioni sono indicate da tag su una riga a sé, ad esempio `[Intro]`, `[Verse 1]`, `[Chorus]`,
`[Bridge]`, `[Outro]`; si possono aggiungere indicazioni come `[Chorus - anthemic]`. I brani strumentali non hanno testo.

### Loop senza stacchi

ACE-Step da solo non riesce a creare un brano la cui fine si attacchi all'inizio: anche con "seamless loop" nel prompt
tende a sfumare alla fine. Quando chiedi un loop, l'agente aggiunge i tag adatti (niente intro, niente finale, energia
costante) e il server crea anche `<nome>_loop.wav`. Il brano viene tagliato a battute intere e la sua ultima battuta
viene fusa con la prima, così la fine scorre nell'inizio e si può ripetere all'infinito (come la musica dei
videogiochi). Si usa il WAV perché l'MP3 aggiunge piccoli silenzi ai bordi che rovinano la ripetizione continua.

### Strumenti

| Strumento | Cosa fa |
|---|---|
| `acestep_status` | ACE-Step è raggiungibile? Modelli caricati, durata massima (es. "8 min"), versioni massime |
| `acestep_ask_song_details` | Modulo (se supportato) o elenco di domande per l'utente |
| `acestep_generate` | Genera il brano (o i brani), loop facoltativo; restituisce i percorsi dei file o un job id |
| `acestep_get_result` | Attende una generazione in corso |
| `acestep_list_songs` | Ultimi brani generati |

## Note

- Una generazione alla volta; mentre l'agente genera, la pagina di ACE-Step nell'app resta occupata fino alla fine.
- La durata massima dipende dalla GPU e dai modelli caricati (l'app la mostra nella barra del menu).
- Nulla esce dal tuo PC: il server parla solo con ACE-Step su `127.0.0.1`. Legge indirizzo, modelli e limiti da
  `server_info.json`, scritto dall'app accanto a `config.json`. `ACESTEP_URL` permette di forzare l'indirizzo.

## Problemi comuni

- *"ACE-Step is not reachable"*: apri l'app e attendi la pagina. Se avvii ACE-Step a mano, aggiungi `--enable-api`.
- L'agente non mostra gli strumenti: riavvialo; controlla che `uv` sia nel PATH o usa il percorso completo.
- Primo avvio lento: uv sta scaricando il pacchetto `mcp` (l'installer lo fa in anticipo).
- Codex dice che il server non è partito in tempo: lascia `startup_timeout_sec = 120`.

Disinstallazione: `uv run mcp\install.py --uninstall`.
