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

Em **Locais**, o dono cadastra cada regiao atendida e o horario de inicio e
fim daquele local. Um local pausado deixa de aparecer no checkout, sem alterar
os pedidos ja registrados.

## Recuperacao de senha do dono

Em **Configuracoes > Seguranca do painel**, o dono cadastra seu e-mail de
recuperacao. Na tela `/entrar`, o link **Esqueci minha senha** envia um codigo
de seis digitos, valido por 15 minutos e utilizavel uma unica vez. O sistema
limita solicitacoes e bloqueia o codigo apos tentativas incorretas repetidas.

Para habilitar o envio, configure no ambiente seguro do servidor ou do Render
as variaveis `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` e
`SMTP_FROM`. Para a porta 587, mantenha `SMTP_USE_TLS=true`; para um provedor
que usa SSL direto na porta 465, use `SMTP_USE_SSL=true` e `SMTP_USE_TLS=false`.
Se utilizar Gmail, use uma senha de aplicativo, nunca a senha normal da conta.
Esses valores nao devem ir para o GitHub.

Sem acesso ao e-mail, a pessoa deve falar com a AG Delivery pelo suporte. A
recuperacao manual deve conferir os dados cadastrais da loja e gerar uma nova
senha; nao aceite senha, codigo temporario ou token enviado por WhatsApp.
Somente apos essa conferencia, o fornecedor pode abrir o Shell do servidor e
executar `py redefinir_senha_dono.py` (ou `python3 redefinir_senha_dono.py` no
Linux). Esse utilitario e exclusivo do terminal e nao abre uma pagina publica.

## Licenca mensal por certificado

O painel do dono possui a aba **Licenca**. Ela mostra um codigo unico da
instalacao. Depois do pagamento da mensalidade, o fornecedor gera um
certificado para esse codigo e envia o texto ao dono pelo canal combinado.
O dono cola o certificado na mesma tela e clica em **Validar certificado**.

O certificado e assinado, tem data de vencimento e nao pode ser reaproveitado
em outra instalacao. Para ativar este controle em uma instalacao nova:

1. Gere uma chave longa e secreta (minimo de 48 caracteres) e salve-a em
   `LICENSE_SIGNING_KEY` tanto no ambiente seguro do servidor como no seu
   computador de manutencao. Nunca envie essa chave ao restaurante nem a
   versione no Git.
2. Entre no painel como dono, abra **Licenca** e copie o codigo da instalacao.
3. No aplicativo local privado **GeradorCertificadosDelivery**, informe o
   codigo da instalacao e a validade. Esse aplicativo nao faz parte deste
   repositorio e nao deve ser enviado ao GitHub.
4. Envie ao dono apenas o texto que comeca com `MDS-LIC1`. Ele deve colar esse
   texto na aba **Licenca** e validar.
5. Depois de testar a ativacao, defina `LICENSE_ENFORCEMENT=true` no servidor.
   Sem certificado valido, novas vendas ficam bloqueadas. O dono ainda pode
   entrar na aba **Licenca** para renovar, e pedidos antigos podem continuar
   sendo acompanhados e entregues.

Este mecanismo impede a alteracao manual da data dentro do painel. Como todo
software hospedado pelo proprio cliente, ele nao protege contra quem tenha
acesso administrativo completo ao servidor, banco de dados e chaves de
ambiente. Para maior controle, mantenha a hospedagem sob a sua administracao.

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

## Venda presencial com Mercado Pago Point

No painel do dono, abra **Configuracoes** e preencha o **Access Token do Point** e o **ID do terminal Point**. Essa credencial fica separada do token do Checkout Pro. A maquininha precisa estar vinculada a mesma conta Mercado Pago e configurada no modo **PDV**.

Em **Nova venda**, informe o cliente ou a mesa, selecione **Cartao na maquininha Point** e conclua. A cobranca aparece no Point e a tela acompanha o resultado; o sistema tambem aceita notificacoes de `order` no mesmo webhook configurado para a instalacao. O botao **PDF 80 mm** gera um comprovante operacional para imprimir pelo driver da Bematech, Elgin i9 ou outra impressora configurada com bobina de 80 mm. Nao e NF-e nem NFC-e.

## Verificacao apos publicar

```bash
curl -fsS https://meninodossonhos.com.br/healthz
sudo journalctl -u sistemavenda -f
```

O primeiro comando deve responder `{"status":"ok"}`. Depois, simule uma notificacao pelo painel Mercado Pago e confirme que ela aparece como entregue.
