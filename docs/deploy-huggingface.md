# Demo no Hugging Face Spaces

O app é Flask (não Streamlit/Gradio), então a demo usa um **Space com SDK Docker**, que é gratuito no plano básico de
CPU. O `Dockerfile` da raiz já faz tudo: instala as dependências, liga o `DEMO_MODE`, aponta para o `sample_bank/`,
cria o banco SQLite no boot (`scripts/init_db.py`) e sobe o app com gunicorn na porta 7860.

## O que muda no modo demo

- O painel de curadoria `/admin` não é registrado (ninguém edita o banco pela web).
- Cookies de sessão com `SameSite=None; Secure`, para funcionar dentro do iframe do Hugging Face.
- Sem `SECRET_KEY` definido, o app gera uma chave aleatória a cada boot.
- O banco SQLite é **compartilhado** entre visitantes (o app é single-user) e **recriado** a cada reinício do Space.

## Passo a passo

1. Em https://huggingface.co/new-space crie um Space:
   - **Space SDK:** Docker → *Blank*
   - **Hardware:** CPU basic (grátis)
   - Visibilidade: Public
2. (Recomendado) Em *Settings → Variables and secrets*, crie o secret `SECRET_KEY` com um valor aleatório longo.
3. Envie o código para o Space. O Space é um repositório git; o `README.md` dele precisa começar com o cabeçalho de
   configuração que está em [`deploy/huggingface/README.md`](../deploy/huggingface/README.md):

   ```bash
   git clone https://huggingface.co/spaces/<seu-usuario>/gmat-focus-trainer hf-space
   # copie para hf-space/ todos os arquivos versionados deste repositório, por exemplo:
   git archive HEAD | tar -x -C hf-space
   cp deploy/huggingface/README.md hf-space/README.md
   cd hf-space
   git add . && git commit -m "Deploy demo" && git push
   ```

4. Acompanhe o build na aba *Logs* do Space. Quando aparecer `Booting worker`, a demo está no ar.
5. Coloque o link do Space no topo do `README.md` deste repositório.

## Testar a imagem localmente (opcional)

Com o Docker Desktop aberto:

```bash
docker build -t gmat-focus-trainer .
docker run --rm -p 7860:7860 -e SECRET_KEY=teste gmat-focus-trainer
```

Abra http://localhost:7860. Localmente, sem HTTPS, o navegador pode recusar o cookie `Secure`; para testar fora do
Hugging Face, rode com `-e DEMO_MODE=0`.
