# 🏛️ Equipo y Memoria Institucional: AI Teacher

Este documento define la estructura del equipo multidisciplinario, los acuerdos fundacionales y las decisiones estratégicas de arquitectura de este workspace. Cualquier nueva sesión de Antigravity debe consultar este archivo para mantener la continuidad del proyecto.

---

## 👥 Miembros del Equipo y Roles

### 1. Dirección y Estrategia
* **💼 CEO (Chief Executive Officer):** 
  * *Misión:* Liderar la visión del producto con mentalidad de startup y rigor de capital de riesgo.
  * *Mandato central:* Velocidad de salida al mercado (*Velocity*) y **presupuesto estrictamente de $0** para infraestructura en fase MVP.
* **🎯 Product Owner (PO):**
  * *Misión:* Definir el *backlog*, *acceptance criteria*, copies de la interfaz y experiencia de usuario.
  * *Prioridad:* Reducir el tiempo hasta el valor (*Time-to-Value*) mediante Action Pills y flujos sin fricción.
* **🔒 CISO (Chief Information Security Officer):**
  * *Misión:* Privacidad de datos, trazabilidad y seguridad contra inyección de prompts.
  * *Reglas aprobadas:* Los archivos originales nunca se persisten; solo vive el texto en memoria; la base de datos vectorial debe almacenarse en rutas locales seguras del usuario fuera de nubes sincronizadas.

### 2. Ingeniería
* **🛠️ CTO (Chief Technology Officer):**
  * *Misión:* Diseñar la arquitectura técnica de costo cero.
  * *Stack técnico:* Streamlit, ChromaDB embebido local en `AppData`, `pypdf`, `langchain` y Google Gemini API (Free Tier).
* **💻 Desarrollador / Antigravity Agent:**
  * *Misión:* Ejecución e implementación limpia de código Python en `app.py`.

### 3. Pedagogía y Aprendizaje
* **🎓 Experto en Educación Moderna:**
  * *Misión:* Andamiaje dinámico, micro-validación en cada turno y prevención de fatiga cognitiva.
* **📐 Diseñador Instruccional y Docente:**
  * *Misión:* Escalamiento por Taxonomía de Bloom (Comprender → Aplicar → Analizar) y **Cierre Activo (Active Closure)** en la Válvula de Escape.

### 4. Consultores de Usuario Final (Testing y Validación)
* **💻 Estudiante de Ingeniería en Sistemas:**
  * *Perfil:* Razonamiento lógico, necesidad de respuestas factuales inmediatas (*Bypass Factual*), odio al tono condescendiente y control del consumo de memoria RAM de su máquina.
* **🩺 Estudiante de Medicina (Interna / 6º Año):**
  * *Perfil:* Volumen masivo de estudio, tolerancia cero a alucinaciones (dosificaciones y mecanismos), simulador de casos clínicos y necesidad de exportación atómica a **Anki**.

---

## 📜 Acuerdos y Decisiones Fundacionales (Sprint 1)

1. **Aesthetic Antigravity:**
   * Modo oscuro profundo (`#0A0A0A`, `#161616`), acentos Cyan (`#00E5FF`), tipografía limpia Inter y tarjetas flotantes `.ag-card`. Sin "AI slop" ni animaciones innecesarias.
2. **Límites de Documentos Aprobados por Stakeholders:**
   * Máximo **15 MB** por archivo.
   * Máximo **100 páginas** por PDF (incentiva el estudio modular por capítulos y cuida la RAM/API).
   * Alerta empática en la UI si el documento supera los límites o si es un PDF escaneado sin texto seleccionable.
3. **Persistencia Protegida contra OneDrive:**
   * La base de datos vectorial local (ChromaDB) se guarda automáticamente en:
     `%LOCALAPPDATA%\AITeacher\chroma_db` (evitando bloqueos de archivo y corrupción por sincronización en la nube).
4. **Orchestrator Prompt V3.1:**
   * **Sección 0 (Bypass Factual):** Respuestas directas sin rodeo socrático para datos puntuales, fórmulas o comandos.
   * **Sección 2 (Válvula de Escape con Cierre Activo):** Al 3er fallo consecutivo (o al presionar el botón `🔓 Dame la respuesta` en la UI), el tutor entrega la explicación directa y exige al estudiante una síntesis con sus propias palabras.
   * **Tono:** Neutral, directo, sin condescendencia (*prohibido "¡Excelente pregunta!"*).
   * **Action Pills Dinámicos:** Cuando hay un documento activo cargado, la pantalla ofrece de inicio: *⚡ Resumen Rápido*, *🎯 Hazme un Quiz* y *🔬 Conceptos Difíciles*.

---

## 🎯 Backlog y Próximos Pasos (Sprint 2)
1. Integración completa de búsqueda semántica (Retrieval) de ChromaDB en cada turno de chat.
2. Botón de exportación de flashcards a formato Anki (.csv / .apkg).
3. Modo simulador de Casos Clínicos / Problemas de Ingeniería.
4. Botón de purga o "Wipe de Memoria" en la interfaz (requisito CISO).
