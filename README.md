#  Coban Archive

Gerenciador de biblioteca de músicas, CDs, vídeos, jogos e galeria de fotos.
Interface desktop construída com Python + PySide6, com cache SQLite para
abertura instantânea mesmo em bibliotecas grandes.

##  Funcionalidades

-  **Músicas** — grid com capas extraídas de tags ID3/Vorbis/MP4
-  **CDs / Álbuns** — agrupamento automático por pasta
-  **Vídeos** — player embutido com efeito CRT, retomada automática
-  **Jogos** — abre ROMs no emulador padrão do sistema
-  **Galeria** — visualização com zoom em tela cheia
-  **Busca global** (`Ctrl+K`) em toda a biblioteca
-  **Shuffle** e **Repeat** (off / all / one)
-  **Atalhos globais**: `Ctrl+Space`, `Ctrl+←/→`, `Ctrl+K`, `F11`
-  **Cache SQLite** com QFileSystemWatcher — abre instantâneo na 2ª execução
-  Temas **escuro** e **claro**
-  Tray icon com controles rápidos
-  Retoma áudio e vídeo de onde parou
-  Log rotativo em `~/.local/share/CobanArchive/` (Linux) ou `%APPDATA%\Coban\CobanArchive\` (Windows)

## 📸 Capturas de Tela

| Tela Principal | Player de Música |
| :---: | :---: |
| <img src="https://i.imgur.com/G2VC0hJ.png" width="400"> | <img src="https://i.imgur.com/0EkdC5W.png" width="400"> |
| **Galeria de Fotos** | **Configurações** |
| <img src="https://i.imgur.com/b1QQsul.png" width="400"> | <img src="https://imgur.com/a/S8pLRrw.png" width="400"> |

## 📦 Instalação

### Requisitos
- Python 3.9+
- Windows, Linux ou macOS

### Instalar

```bash
git clone https://github.com/seu-usuario/coban-archive.git
cd coban-archive
pip install -r requirements.txt
python main.py
