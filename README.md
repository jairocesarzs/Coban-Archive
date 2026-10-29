# Coban Archive

Central de mídia pessoal para desktop, feita em **Python + PySide6 (Qt)**. Em vez de abrir um programa para cada tipo de arquivo, você organiza e reproduz seu acervo de músicas, CDs, vídeos, jogos e fotos em um único app, com visual próprio e player sempre à mão.

## Funcionalidades

### 🎵 Músicas
- Biblioteca com visualização em **grade** (com capas) ou **lista**
- Leitura de metadados e capas embutidas (MP3, FLAC, OGG, M4A, WAV) via *mutagen*
- Busca por nome, artista ou álbum
- Várias pastas de música configuráveis
- Ao reabrir o app, ele lembra a última faixa e a playlist
- Capa do álbum ampliável em tela cheia

### 💿 CDs (Disk)
- Cada pasta de álbum vira um "CD" na estante, com capa
- Reproduz o álbum completo como playlist
- Busca por álbum

### 🎬 Vídeos
- Reprodução dentro de uma **moldura de TV retrô** com efeito de linhas de varredura (scanlines)
- Suporte a muitos formatos: MP4, MKV, AVI, MOV, WMV, WEBM, RMVB, RM, FLV, VOB, entre outros
- **Retomar de onde parou**, com marcação de "Assistido" e do ponto de retomada em cada vídeo
- Tela cheia (F11 / duplo clique)
- Varredura das pastas em segundo plano, sem travar a interface

### 🎮 Jogos
- Estante de jogos (`.gba`, `.ciso`) com capas encontradas automaticamente na pasta do jogo
- Abre o jogo no programa associado do sistema (por exemplo, seu emulador)
- Pausa o áudio e o vídeo ao abrir um jogo

### 🖼️ Galeria de fotos
- Até **5 pastas** configuráveis, com filtro por pasta
- Miniaturas em grade e visualizador em tela cheia

### 🎧 Player integrado
- Barra fixa no rodapé: capa, título, artista/ano, anterior/play/próxima, progresso e volume
- Seleção do dispositivo de saída de áudio
- Equalizador com efeitos BBE e filtros de frequência *(em desenvolvimento)*

### ⚙️ Personalização
- **Tema claro e escuro**, com ícones que se adaptam a cada um
- Menu lateral à esquerda ou à direita
- Todas as pastas (músicas, CDs, vídeos, jogos, galeria) configuráveis pela própria interface

### ⌨️ Atalhos de teclado
| Atalho | Ação |
|---|---|
| `Ctrl+Espaço` | Play / pausa |
| `Ctrl+N` / `Ctrl+B` | Próxima / anterior |
| `Ctrl+←` / `Ctrl+→` | Voltar / avançar 5 s |
| `Ctrl+↑` / `Ctrl+↓` | Volume + / − |
| `Ctrl+M` | Mudo |
| `Ctrl+F` | Buscar |
| `F11` | Tela cheia do vídeo |
| Teclas de mídia | Play, próxima, anterior |

### 🚀 Desempenho
- Cache de miniaturas em disco
- Varredura de pastas e geração de miniaturas em threads separadas
- Configurações salvas automaticamente

## Tecnologias
Python 3 · PySide6 (Qt Multimedia) · Pillow · mutagen

## Como executar
```bash
pip install -r requirements.txt
python main.py
```
