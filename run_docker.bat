@echo off
REM ==================================================================
REM  Modelo espacio-temporal en Docker. Doble clic = menu.
REM  Se monta esta carpeta en /app: config\, data\ y las salidas quedan aqui.
REM
REM  Sin menu (p.ej. desde el Programador de tareas):
REM    run_docker.bat rutina                 descarga lluvia de ayer + prediccion
REM    run_docker.bat rutina 2026-01-15      idem para una fecha
REM    run_docker.bat prediccion 2026-01-15  solo prediccion
REM    run_docker.bat test-gee               prueba la cuenta de servicio GEE
REM    run_docker.bat build                  reconstruye la imagen
REM    run_docker.bat scripts\...\algo.py --args   cualquier script .py / .R
REM ==================================================================
setlocal
cd /d "%~dp0"
set IMG=modelo-espacio-temporal
set MENU=0
set RC=0

docker info >nul 2>&1 || (echo Docker no esta corriendo. Abre Docker Desktop y vuelve a intentar. & set RC=1 & goto fin)

if /i "%~1"=="build" goto build
docker image inspect %IMG% >nul 2>&1 || (echo Construyendo la imagen, la primera vez tarda varios minutos... & docker build -t %IMG% .) || (set RC=1 & goto fin)

REM  Token de NASA Earthdata (lo crea la opcion "Login NASA"); .netrc esta en .gitignore
if not exist "config\.netrc" type nul > "config\.netrc"

set ARGS=%*
set TTY=-i
if not "%ARGS%"=="" goto correr

set MENU=1
set TTY=-it
:menu
echo.
echo   1) Probar conexion con Google Earth Engine
echo   2) Descargar lluvia historica IMERG Final (GEE)   -^> data\lluvia_historica_gee
echo   3) Rutina diaria: lluvia NASA (ultimos 31 dias) + prediccion
echo   4) Solo prediccion (con el buffer de lluvia actual)
echo   5) Login NASA Earthdata (una sola vez)
echo   6) Consola dentro del contenedor (bash)
echo   7) Reconstruir la imagen Docker
echo.
set OPC=
set /p OPC="Opcion [1-7, Enter = salir]: "
if "%OPC%"=="" endlocal & exit /b 0
if "%OPC%"=="1" set ARGS=test-gee& goto correr
if "%OPC%"=="2" goto historica
if "%OPC%"=="3" goto rutina
if "%OPC%"=="4" goto prediccion
if "%OPC%"=="5" set ARGS=login-nasa& goto correr
if "%OPC%"=="6" set ARGS=bash& goto correr
if "%OPC%"=="7" goto build
goto menu

:historica
set INI=
set FIN=
set /p INI="Fecha inicial YYYY-MM-DD: "
set /p FIN="Fecha final YYYY-MM-DD (exclusiva): "
if "%INI%"=="" goto menu
if "%FIN%"=="" goto menu
set ARGS=scripts/01_descarga_lluvia/descargar_imerg_gee_historico.py --slopes data/Unidades_ladera/Unidades_ladera_comp_1500k.shp --out data/lluvia_historica_gee --inicio %INI% --fin %FIN%
goto correr

:rutina
set F=
set /p F="Fecha a predecir YYYY-MM-DD (Enter = ayer UTC): "
set ARGS=rutina %F%
goto correr

:prediccion
set F=
set /p F="Fecha a predecir YYYY-MM-DD (Enter = hoy): "
set ARGS=prediccion %F%
goto correr

:correr
echo.
echo Ejecutando en Docker: %ARGS%
echo.
docker run --rm %TTY% ^
  -v "%CD%:/app" ^
  -v "%CD%\config\.netrc:/root/.netrc" ^
  -e EARTHDATA_USERNAME -e EARTHDATA_PASSWORD ^
  %IMG% %ARGS%
set RC=%ERRORLEVEL%
goto fin

:build
docker build -t %IMG% .
set RC=%ERRORLEVEL%

:fin
echo.
echo Codigo de salida: %RC%
if "%MENU%"=="1" pause
endlocal & exit /b %RC%
