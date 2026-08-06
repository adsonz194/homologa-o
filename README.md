# Sistema de Delivery

Aplicacao Flask para cardapio, pedidos, estoque, painel interno e Checkout Pro do Mercado Pago.

## Fluxo do cliente

1. Acessa `/` e abre diretamente o delivery.
2. Escolhe produtos disponiveis, informa endereco e seleciona Pix, credito ou debito.
3. O pagamento e realizado no ambiente seguro do Mercado Pago.
4. Quando aprovado, o pedido passa para `FILA_DE_ESPERA` e o cliente pode ser direcionado ao WhatsApp.
5. O cliente acompanha a entrega com o codigo aleatorio exibido na tela do pedido.

O painel e acessado em `/entrar`. O dono cadastra os produtos e funcionarios; pedidos e vendas podem ser operados por funcionarios autenticados.

O dono encontra a aba **Configuracoes** apos entrar no painel. Nela, pode
definir WhatsApp, URL publica, taxa de entrega e as credenciais de producao do
Mercado Pago. Os segredos salvos por essa tela sao cifrados e nunca voltam a
ser exibidos no navegador. A taxa inicial e R$ 6,00 por pedido e aparece no
carrinho antes do cliente finalizar.

## Executar localmente

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
py criar_admin.py
py app.py
```

Abra `http://localhost:5000`. Para receber retorno automatico, webhook e pagamentos reais, `BASE_URL` precisa ser um endereco HTTPS publico.

## Producao na VPS

Os arquivos em `deploy/` sao modelos para Ubuntu com Nginx e systemd.

1. No provedor do dominio, crie registros DNS `A` para `meninodossonhos.com.br` e `www`, apontando para o IP publico da VPS.
2. Na VPS, copie o projeto para `/opt/sistemavenda`, crie o usuario de servico `delivery` e o diretorio de dados:

   ```bash
   sudo adduser --system --group --home /opt/sistemavenda delivery
   sudo mkdir -p /opt/sistemavenda /var/lib/sistemavenda /etc/sistemavenda
   sudo chown -R delivery:delivery /opt/sistemavenda /var/lib/sistemavenda
   ```

3. Como usuario `delivery`, crie o ambiente e instale as dependencias:

   ```bash
   cd /opt/sistemavenda
   python3 -m venv .venv
   .venv/bin/pip install -r requirements-production.txt
   ```

4. Copie `deploy/sistemavenda.env.example` para `/etc/sistemavenda/sistemavenda.env`, preencha apenas as credenciais de producao e proteja o arquivo:

   ```bash
   sudo cp deploy/sistemavenda.env.example /etc/sistemavenda/sistemavenda.env
   sudo chown root:delivery /etc/sistemavenda/sistemavenda.env
   sudo chmod 640 /etc/sistemavenda/sistemavenda.env
   ```

5. Instale e inicie o servico:

   ```bash
   sudo cp deploy/sistemavenda.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now sistemavenda
   sudo systemctl status sistemavenda
   ```

6. Instale Nginx e Certbot, publique a configuracao e gere o HTTPS:

   ```bash
   sudo apt update
   sudo apt install -y nginx certbot python3-certbot-nginx
   sudo cp deploy/nginx-meninodossonhos.conf /etc/nginx/sites-available/sistemavenda
   sudo ln -s /etc/nginx/sites-available/sistemavenda /etc/nginx/sites-enabled/sistemavenda
   sudo nginx -t
   sudo systemctl reload nginx
   sudo certbot --nginx -d meninodossonhos.com.br -d www.meninodossonhos.com.br
   ```

Nao exponha a porta 8000 ou rode o servidor de desenvolvimento Flask na internet. Libere apenas SSH, HTTP e HTTPS no firewall da VPS.

## Mercado Pago e webhook

No painel de desenvolvedores do Mercado Pago, configure o evento **Pagamentos** para:

```text
https://meninodossonhos.com.br/webhook/mercadopago
```

Copie a **assinatura secreta** gerada pelo painel para `MERCADOPAGO_WEBHOOK_SECRET`. O sistema valida a assinatura HMAC antes de consultar a API do Mercado Pago e atualizar o status do pedido. Use credenciais de producao somente em producao e mantenha todas as chaves fora do Git.

O Mercado Pago exige URL HTTPS publica para notificacoes e retornos. Em desenvolvimento, use credenciais de teste e deixe `BASE_URL=http://localhost:5000`.

## Verificacao apos publicar

```bash
curl -fsS https://meninodossonhos.com.br/healthz
sudo journalctl -u sistemavenda -f
```

O primeiro comando deve responder `{"status":"ok"}`. Depois, simule uma notificacao pelo painel Mercado Pago e confirme que ela aparece como entregue.
