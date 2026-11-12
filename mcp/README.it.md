# Music Studio MCP for ACE-Step

[English](README.md) · **Italiano**

Nome tecnico: `music-studio-mcp-for-ace-step` · Versione **1.1.1**

Un server [MCP](https://modelcontextprotocol.io) che permette a un agente AI di creare musica con ACE-Step 1.5 sul tuo
PC. Descrivi il brano in chat; l'agente ti chiede quale modalità usare (Simple, Custom, Remix, Repaint…), ti fa
qualche domanda (stile, voce, lingua, durata indicativa, loop, file audio…), scrive i tag di stile e il testo, ti
mostra un riepilogo, ti chiede il nome del file e, dopo il tuo OK, genera il brano tramite l'app
**Music Studio for ACE-Step**.

> [!TIP]
> **Esclusiva di questo MCP: brani che si ripetono in loop senza stacchi.** ACE-Step e l'app non possono crearli
> (ACE-Step sfuma alla fine anche quando gli si chiede un loop); con l'MCP chiedi un brano "che vada in loop
> all'infinito" e ricevi un unico `.wav` la cui fine scorre nell'inizio — vedi [Loop senza stacchi](#loop-senza-stacchi).

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
2. Chiedi all'agente con parole tue, senza bisogno di comandi speciali, ad esempio:
   - *"Usa Music Studio per farmi un brano lo-fi rilassante di 1 minuto per studiare"*
   - *"Scrivi e genera una canzone pop italiana sull'estate, voce femminile, circa 2 minuti"*
   - *"Fai un remix di C:\Musica\mia-canzone.mp3 in versione folk acustica"*
3. L'agente controlla ACE-Step e ti chiede quale **modalità** usare (salta la domanda se la tua richiesta lo dice già).
4. Fa solo le domande di quella modalità:
   - stile, voce e lingua;
   - **durata indicativa con il massimo tra parentesi** (es. *"Durata? (max 8 min)"*), oppure la lasci scegliere ad ACE-Step;
   - **loop senza stacchi** (facoltativo);
   - tempo e tonalità;
   - numero di versioni;
   - i file audio che servono alla modalità.
5. Mostra una tabella di riepilogo e attende il tuo OK; poi, come **ultima domanda**, chiede il **nome del file**.
6. Genera (un brano di 30–60 s richiede circa un minuto; l'app mostra una finestrella di avanzamento) e ti dice dove si
   trovano i file.

### Modalità

| Modalità | Cosa fa | Serve |
|---|---|---|
| **Simple** | Descrivi il brano a parole; ACE-Step sceglie stile, testo, durata, tempo e tonalità | — |
| **Custom** | Controllo completo: stile, testo, durata, tempo, tonalità | **audio di riferimento** facoltativo per imitarne il suono |
| **Remix** | Trasforma un brano esistente in un altro stile mantenendone struttura e melodia (fedeltà 0.2 libera – 0.8 fedele) | un **brano di partenza** |
| **Repaint** | Rigenera solo un tratto (dal secondo X al secondo Y) e lascia intatto il resto | un **brano di partenza** |
| **Extract** | Isola uno strumento o la voce | un brano di partenza, solo **modelli base** |
| **Lego** | Aggiunge o sostituisce una traccia (es. batteria) | un brano di partenza, solo **modelli base** |
| **Complete** | Aggiunge gli strumenti mancanti a un brano parziale | un brano di partenza, solo **modelli base** |

Extract, Lego e Complete compaiono solo quando ACE-Step usa un modello *base* (il modello turbo offre le prime quattro).

### File audio (brano di partenza, audio di riferimento)

L'agente non può leggere i file allegati in chat: quando te lo chiede **incolla il percorso completo** del file, ad
esempio `C:\Users\Nome\Musica\canzone.mp3` (negli agenti da terminale puoi trascinare il file nella finestra e il
percorso si scrive da solo). Puoi anche chiedere all'agente di **elencare i tuoi brani recenti** e sceglierne uno
come brano di partenza.

### Nomi dei file e dove vengono salvati i brani

ACE-Step dà ai file nomi casuali; il server rinomina il brano con il nome che scegli. Un brano = **un solo file**,
`<nome>.mp3` (`<nome>.wav` per un loop). Solo se chiedi più versioni dello stesso brano le altre si chiamano
`<nome>_2.mp3`, `<nome>_3.mp3`, … Vengono salvati nella cartella dei risultati di ACE-Step, in
`gradio_outputs\mcp_<data>_<ora>_<nome>\` (insieme ai file accessori di ACE-Step); l'agente ti dice il percorso
completo, e *Apri cartella dei brani generati* nel menu dell'app apre `gradio_outputs`.

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
costante) e ricevi comunque **un solo file**, `<nome>.wav`, già pronto per il loop: il brano viene tagliato a battute
intere e la sua ultima battuta viene fusa con la prima, così la fine scorre nell'inizio e si può ripetere
all'infinito (come la musica dei videogiochi). Si usa il WAV perché l'MP3 aggiunge piccoli silenzi ai bordi che
rovinano la ripetizione continua.

### Strumenti

| Strumento | Cosa fa |
|---|---|
| `acestep_status` | ACE-Step è raggiungibile? Modelli caricati, durata massima (es. "8 min"), versioni massime, modalità disponibili |
| `acestep_ask_song_details` | Le domande per la modalità scelta (un modulo per Custom nei client che lo supportano) |
| `acestep_generate` | Genera nella modalità scelta con il nome scelto, loop facoltativo; restituisce percorsi e cartella, oppure un job id |
| `acestep_get_result` | Attende una generazione in corso |
| `acestep_list_songs` | Ultimi brani generati (per scegliere il brano di partenza di Remix/Repaint) |

La modalità Simple e Custom senza audio di riferimento usano l'API REST di ACE-Step; le modalità con file audio usano
la funzione di generazione della pagina di ACE-Step, i cui parametri il server rilegge dalla pagina ogni volta.

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
