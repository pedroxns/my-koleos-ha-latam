
## v0.3.4 pre-upload polish

- Entity IDs for new installs are suggested as `sensor.koleos_*`, `switch.koleos_*`, `button.koleos_*`, etc.
- Device name simplified to `Koleos` instead of `Renault Koleos ...`.
- Setup form simplified: only redirect URL/code and country. Advanced/default values are handled internally or in Options.
- The integration intentionally does not collect the Renault account password inside Home Assistant; login remains on the official Renault/Gigya page.

# My Koleos LATAM - Home Assistant custom integration

Versão experimental v0.3.4 `com_ac_final` / `brand_fix`.

## Mudanças desta versão

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


## Brand assets v0.3.4

Atualizado para usar os arquivos fornecidos pelo usuário em `custom_components/my_koleos/brand/`: `icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`, além de variantes `dark_*`.
