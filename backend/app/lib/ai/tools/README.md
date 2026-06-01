Tools are intentionally not connected to the current `/api/chat` path.

Keep future tool schemas and registration code in this package so tool calling
can be added behind `AIService` without changing API routes or frontend request
shape.
