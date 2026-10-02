# Runtime Read TEST: recuperación tras rollback y preflight de ambos roles

Estado: diseño propuesto para revisión. No autoriza IAM, GitHub Actions ni CloudFormation.

## Incidente comprobado

La ejecución protegida de TEST `37076527573`, asociada a la revisión `37076030592`, intentó cambiar únicamente `ConfigRuntimeReadFunction.Code`. CloudFormation devolvió `AccessDenied` en `s3:GetObjectVersion` para el rol `zoolanding-config-runtime-read-test-cfn-exec` sobre el paquete del SHA `06b38c243ed5df6a1bd94a6d2cffd0b9c692b34f`. El rol GitHub tenía permiso para ese SHA, pero la política del rol CloudFormation conservaba dos prefijos anteriores. El cambio se revirtió: la pila está en `UPDATE_ROLLBACK_COMPLETE`, sin change sets, conserva ocho identidades físicas, y el alias `live` sigue en la versión 4 con el mismo `CodeSha256`.

`tools/native_runtime_release.py` acepta únicamente `CREATE_COMPLETE` y `UPDATE_COMPLETE` en `baseline()` y `live_test_zip()`. Por ello, aunque el rollback terminó, el operador actual rechaza una revisión nueva antes de crear un change set. El preflight previo comprobó el rol GitHub, pero no el rol CloudFormation. Las políticas por SHA volverían a quedar obsoletas al promover el parche de código a un SHA TEST nuevo.

## Decisión y límites

1. Aceptar `UPDATE_ROLLBACK_COMPLETE` **solo para la pila TEST** en las dos lecturas del operador. Rechazar todos los estados en curso o fallidos. Antes de usar ese estado, exigir la identidad de la pila y su rol CloudFormation, ocho recursos con estados completos, cero change sets activos, plantilla Original y Processed compatibles con la fuente protegida, parámetros y outputs sin cambios, función `Active`/`Successful`, y alias `live` con paquete y digest verificados. El snapshot seguirá sellando estos datos para que cualquier cambio entre review y execute invalide el digest.
2. Cambiar en AWS TEST únicamente la política inline `ThnRetainedTestRelease20260928` de los dos roles de despliegue. En el rol GitHub, los tres statements de lectura, lectura versionada y escritura AES256 de paquetes usarán `arn:aws:s3:::zoolanding-config-payloads-test/system/thn-runtime/releases/*`. En el rol CloudFormation, solo `ReadExactRuntimeReleaseVersions` usará ese mismo recurso. Conservar acciones, condiciones, demás statements y la excepción exacta de lectura de rollback. El operador seguirá exigiendo SHA de fuente de 40 hexadecimales, ZIP con SHA-256, objeto S3 versionado, lectura de vuelta byte a byte, paquete idéntico a `live` cuando corresponda y change set de un solo cambio de código. El wildcard permite paquetes dentro de ese prefijo TEST; no concede acceso a otros prefijos, buckets ni producción.
3. Añadir un preflight de solo lectura, parametrizado por SHA, digest ZIP y versión S3 cuando ya exista. Comprobar cuenta y región, SHA/árbol/selector, pila, ocho identidades, alias, objeto y versión, políticas efectivas de **ambos** roles mediante `iam:SimulatePrincipalPolicy`, y el candidato de plantilla contra las respuestas reales de AWS. Simular `GetObject`, `PutObject` con AES256 y `GetObjectVersion` para el rol GitHub; `GetObjectVersion` para el rol CloudFormation; denegaciones fuera del prefijo y con cifrado o VersionId inválidos. La simulación no sustituye la revisión protegida de CloudFormation, pero detiene antes del Action el fallo concreto observado.

## Secuencia de implementación y verificación

1. Escribir pruebas que reproduzcan el rechazo actual de `UPDATE_ROLLBACK_COMPLETE` y la omisión del permiso del segundo rol. Verlas fallar, aplicar el cambio mínimo y ejecutar la suite local, `sam validate` y `actionlint`.
2. Integrar el operador por PR `dev → test` solo con CI y el job AWS omitido. Obtener el SHA TEST definitivo antes de revisar IAM; actualizar el selector exacto solo después de verificar ese SHA, árbol y hash del workflow.
3. Preparar dos documentos IAM candidatos desde las políticas **actuales** y comparar de forma canónica que cambian solo los cuatro recursos IAM indicados. Simularlos y mostrar sus hashes e inventario. Solicitar autorización específica antes de `put-role-policy`; volver a leer y simular los documentos aplicados.
4. Ejecutar el preflight local completo, incluidas respuestas AWS actuales y el artefacto generado para el SHA definitivo. Si falla cualquiera de las comprobaciones, corregir antes de GitHub Actions. Lanzar una única revisión protegida `Deploy Test`, `execution=review`, con autorización separada. Exigir un `Modify` sin reemplazo de `ConfigRuntimeReadFunction.Code`, revisar digest y pedir autorización nueva antes de `execute`.
5. Tras ejecutar, verificar estado `UPDATE_COMPLETE`, ocho identidades, alias `live`, código y consulta permitida. Promover a MAIN y revisar producción solo con el artefacto elegible de ese deploy TEST y las aprobaciones respectivas.

## Alternativas consideradas

- Mantener prefijos por SHA y actualizar **ambos** roles después de cada promoción. Conserva el alcance más estricto de IAM, pero exige dos cambios manuales por release y deja abierta la misma omisión si el preflight no se ejecuta.
- Forzar `UPDATE_COMPLETE` con una actualización manual de la pila. Añade una mutación sin relación con el paquete y evita corregir el rechazo del operador; se descarta.

## Criterio de aceptación

El preflight demuestra permisos efectivos de los dos roles sobre el objeto y versión exactos y rechaza los casos negativos. El operador acepta el rollback estable de TEST y rechaza estados no estables. Ninguna prueba o revisión modifica producción. El review real muestra solo el código de la función; el execute autorizado termina en `UPDATE_COMPLETE` sin cambiar las otras identidades y conserva la respuesta del blog. Ante cualquier diferencia de inventario, política, versión, hash o alias, se detiene el flujo antes de otra ejecución.
