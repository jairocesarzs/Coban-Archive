##  Coban Archive

Gerenciador de biblioteca de músicas, CDs, vídeos, jogos e galeria de fotos.
Interface desktop construída com Python + PySide6, com cache SQLite para abertura instantânea mesmo em bibliotecas grandes.

## Funcionalidades

### Mídia e Biblioteca
- **Músicas:** Grid com capas extraídas de tags ID3, Vorbis e MP4.
- **CDs e Álbuns:** Agrupamento automático por pasta.
- **Vídeos:** Player embutido com efeito CRT e retomada automática.
- **Jogos:** Abertura de ROMs no emulador padrão do sistema.
- **Galeria:** Visualização de imagens com zoom em tela cheia.

### Interface e Controles
- **Busca Global:** Acesso rápido a toda a biblioteca via `Ctrl+K`.
- **Playback:** Controles de Shuffle (aleatório) e Repeat (repetição).
- **Atalhos:** Controle total via teclado (`Ctrl+Space`, `Ctrl+←/→`, `F11`).
- **Temas:** Interface adaptável com opções escura e clara.
- **Bandeja (Tray):** Controles de reprodução rápida na barra de tarefas.

### Performance e Sistema
- **Cache Local:** Integração com SQLite e `QFileSystemWatcher` para carregamento instantâneo.
- **Retomada:** Salva e continua o áudio e vídeo de onde parou.
- **Logs:** Registro rotativo em `%APPDATA%\Coban\CobanArchive\` (Windows) ou equivalente.

##  Capturas de Tela

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

##  Instalação

### Requisitos
- Python 3.9+
- Windows, Linux ou macOS

### Instalar

```bash
git clone https://github.com/seu-usuario/coban-archive.git
cd coban-archive
pip install -r requirements.txt
python main.py

