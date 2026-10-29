<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/93cac3c9-3ffc-4eab-b6c2-b371dc61b47c" /># 🎵 Coban Archive

Gerenciador de biblioteca de músicas, CDs, vídeos, jogos e galeria de fotos.
Interface desktop construída com Python + PySide6, com cache SQLite para abertura instantânea mesmo em bibliotecas grandes.

## 📸 Capturas de Tela

<p align="center">
  <img src="https://i.imgur.com/rT4ltny.png" width="1000" alt="Tela Principal">
</p>

<p align="center">
  <img src="https://i.imgur.com/PWy0UCv.png" width="1000" alt="Player de Música">
</p>

<p align="center">
  <img src="https://i.imgur.com/a0nck3t.png" width="1000" alt="Galeria de Fotos">
</p>

<p align="center">
  <img src="https://i.imgur.com/Hwv9LgQ.png" width="1000" alt="Configurações">
</p>

## ✨ Funcionalidades

- 🎵 **Músicas** — grid com capas extraídas de tags ID3/Vorbis/MP4
- 💿 **CDs / Álbuns** — agrupamento automático por pasta
- 🎬 **Vídeos** — player embutido com efeito CRT, retomada automática
- 🎮 **Jogos** — abre ROMs no emulador padrão do sistema
- 🖼 **Galeria** — visualização com zoom em tela cheia
- 🔍 **Busca global** (`Ctrl+K`) em toda a biblioteca
- 🔀 **Shuffle** e **Repeat** (off / all / one)
- ⌨️ **Atalhos globais**: `Ctrl+Space`, `Ctrl+←/→`, `Ctrl+K`, `F11`
- 💾 **Cache SQLite** com QFileSystemWatcher — abre instantâneo na 2ª execução
- 🎨 Temas **escuro** e **claro**
- 🌐 Tray icon com controles rápidos
- 🎯 Retoma áudio e vídeo de onde parou
- 📝 Log rotativo em `~/.local/share/CobanArchive/` (Linux) ou `%APPDATA%\Coban\CobanArchive\` (Windows)

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
