
# My Koleos LATAM - Home Assistant custom integration

Created with heavy AI support, use it at your own risk.

Renault Koleos is currently only working with Renault My Koleos app, but there are no HA integrations for this app, so I reversed engineered the Android app with AI support

After install and Haos restart, add the integration and use the given URL to access Renaults page and autenticate with your e-mail and password, after the login the URL will change, copy the new one and paste it at the integration popup.

`All entities wiil be created with "domain.renault_koleos_*" name pattern.`

## v0.3.6
`Add license info`

## v0.3.5

- Fix Koleos location coordinates decoding scale;
`The old version was using a /10.000.000 scale for lat/long coordiantes, the new one uses the correct /3/600.000.`


## Changes in this version

- Fixes remote climate control to use the confirmed flow from the My Koleos LATAM app:

- `PUT /remote-control/vehicle/telematics/{vin}`

- `serviceId: RCE_2`

- `command: start` / `stop`

- `creator: tc`

- `operationScheduling.duration = minutes * 6`

- `serviceParameters` with real serialized keys: `rce.temp` and `rce.conditioner`

- Removes the use of PAA for the instant climate control button/service.

- Adds direct services:

- `my_koleos.climate_start`

- `my_koleos.climate_stop`

- Maintains compatibility with `my_koleos.remote_command` using `command: hvac_start` / `hvac_stop`.

- Adds `switch` entity for remote climate control. ## Services

Start AC for 10 minutes at 22°C:

```yaml
service: my_koleos.climate_start
data:

temperature: 22
minutes: 10
```

Turn off AC:

```yaml
service: my_koleos.climate_stop
data: {}
```

With multiple entries, specify `entry_id` or `vin`:

```yaml
service: my_koleos.climate_start
data:

entry_id: "YOUR_ENTRY_ID"
temperature: 22
minutes: 10
```

## Notes

- **Experimental remote commands** must be enabled in the integration options.

- The climate control command is not marked as sensitive, but it still physically activates the car.

- The lock/unlock/start commands remain protected by the sensitive commands option.

- After copying the files, restart Home Assistant.

## v0.3.4 - Logo/Brand Image Correction

Home Assistant 2026.3+ expects local brand images in:

```text
custom_components/my_koleos/brand/icon.png
custom_components/my_koleos/brand/logo.png

```

This version adds the correct `brand/` folder. The previous version used `brands/`, which is not the path used by the frontend for recent custom integrations.

After copying the integration:

1. Restart Home Assistant.

2. Reload the page with a clear cache, if necessary.

3. Test in an authenticated browser:

```text
/api/brands/integration/my_koleos/icon.png?placeholder=no
/api/brands/integration/my_koleos/logo.png?placeholder=no
```

If it returns a 404 error, HA is not yet reading the `brand/` folder or the HA version is earlier than 2026.3.

## Installation via HACS as a custom repository

1. In Home Assistant, open **HACS**.

2. Three-dot menu in the upper right corner.

3. **Custom repositories**.

4. Paste the GitHub repository URL.

5. Category: **Integration**.

6. Click **ADD** and install.

After installation, restart Home Assistant.

--------------------------------------------------------------
--------------------------------------------------------------

## v0.3.6
- Adicionadas informações de licensa.

## v0.3.5

- Correção de fator de correção para decodificação da localização;
  - `A versão antiga usava a escala /10.000.000, a nova versão corrige a escala para /36.600.000`

## v0.3.4

- Corrige a climatização remota para usar o fluxo confirmado do app My Koleos LATAM:
  - `PUT /remote-control/vehicle/telematics/{vin}`
  - `serviceId: RCE_2`
  - `command: start` / `stop`
  - `creator: tc`
  - `operationScheduling.duration = minutos * 6`
  - `serviceParameters` com chaves reais serializadas: `rce.temp` e `rce.conditioner`
- Remove o uso de PAA para o botão/serviço de climatização imediata.
- Adiciona serviços diretos:
  - `my_koleos.climate_start`
  - `my_koleos.climate_stop`
- Mantém compatibilidade com `my_koleos.remote_command` usando `command: hvac_start` / `hvac_stop`.
- Adiciona entidade `switch` para climatização remota.

## Serviços

Ligar AC por 10 minutos em 22 °C:

```yaml
service: my_koleos.climate_start
data:
  temperature: 22
  minutes: 10
```

Desligar AC:

```yaml
service: my_koleos.climate_stop
data: {}
```

Com múltiplas entradas, informe `entry_id` ou `vin`:

```yaml
service: my_koleos.climate_start
data:
  entry_id: "SEU_ENTRY_ID"
  temperature: 22
  minutes: 10
```

## Observações

- É necessário habilitar **comandos remotos experimentais** nas opções da integração.
- O comando de climatização não é marcado como sensível, mas ainda aciona o carro fisicamente.
- Os comandos de travar/destravar/partida continuam protegidos pela opção de comandos sensíveis.
- Após copiar os arquivos, reinicie o Home Assistant.

## v0.3.4 - Correção de logotipo/brand images

O Home Assistant 2026.3+ espera imagens locais de marca em:

```text
custom_components/my_koleos/brand/icon.png
custom_components/my_koleos/brand/logo.png
```

Esta versão adiciona a pasta `brand/` correta. A versão anterior trazia `brands/`, que não é o caminho usado pelo frontend para custom integrations recentes.

Após copiar a integração:

1. Reinicie o Home Assistant.
2. Recarregue a página com cache limpo, se necessário.
3. Teste no navegador autenticado:

```text
/api/brands/integration/my_koleos/icon.png?placeholder=no
/api/brands/integration/my_koleos/logo.png?placeholder=no
```

Se retornar 404, o HA ainda não está lendo a pasta `brand/` ou a versão do HA é anterior a 2026.3.


## Instalação via HACS como repositório customizado

1. No Home Assistant, abra **HACS**.
2. Menu de três pontos no canto superior direito.
3. **Custom repositories**.
4. Cole a URL do repositório GitHub.
5. Categoria: **Integration**.
6. Clique em **ADD** e instale.

Após a instalação, reinicie o Home Assistant.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
