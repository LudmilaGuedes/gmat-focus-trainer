# Demo no Render (plano gratuito)

O app é Flask com SQLite, empacotado no `Dockerfile` da raiz. O [`render.yaml`](../render.yaml) descreve o serviço
para o Render: um *web service* Docker no plano gratuito, com `DEMO_MODE=1` e um `SECRET_KEY` gerado pelo próprio
Render. No boot, o contêiner cria o banco SQLite com o banco de exemplo (`scripts/init_db.py`) e sobe o app com
gunicorn.

## O que muda no modo demo

- O painel de curadoria `/admin` não é registrado (ninguém edita o banco pela web).
- Cookies de sessão só trafegam por HTTPS.
- O banco SQLite é **compartilhado** entre visitantes (o app é single-user) e **recriado** a cada deploy ou
  reinício.
- No plano gratuito, o serviço "dorme" depois de ~15 minutos sem acesso; o primeiro acesso seguinte leva cerca de
  1 minuto para acordar.

## Passo a passo

1. Crie uma conta em https://render.com (dá para entrar com a conta do GitHub).
2. No painel, clique em **New → Blueprint**.
3. Conecte o GitHub e escolha o repositório `gmat-focus-trainer`.
4. O Render lê o `render.yaml` e mostra o serviço `gmat-focus-trainer` (plano Free). Clique em **Deploy Blueprint**.
5. Acompanhe o build em **Logs** (alguns minutos na primeira vez). Quando aparecer `Booting worker`, a demo está no ar
   em `https://gmat-focus-trainer.onrender.com` (ou num endereço parecido, se esse nome já estiver em uso).
6. Coloque o link no topo do `README.md`.

Depois disso, cada push na branch `main` gera um novo deploy automaticamente.

## Testar a imagem localmente (opcional)

Com o Docker Desktop aberto:

```bash
docker build -t gmat-focus-trainer .
docker run --rm -p 10000:10000 -e DEMO_MODE=0 gmat-focus-trainer
```

Abra http://localhost:10000. `DEMO_MODE=0` é necessário localmente porque, sem HTTPS, o navegador não guarda o
cookie de sessão marcado como `Secure`.
