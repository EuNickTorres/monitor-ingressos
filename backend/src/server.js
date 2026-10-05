require("dotenv").config();

const express = require("express");
const cors = require("cors");
const connectDB = require("./db");
const routes = require("./routes");

const PORT = process.env.PORT || 3000;

const app = express();

app.disable("x-powered-by");
app.use(cors());
app.use(express.json({ limit: "32kb" }));
app.use("/", routes);

app.use((err, req, res, next) => {
  console.error(`[${req.method} ${req.originalUrl}]`, err.message);
  res.status(500).json({ erro: "Erro interno do servidor" });
});

connectDB()
  .then(() => {
    app.listen(PORT, () => {
      console.log(`Servidor rodando na porta ${PORT} [${process.env.NODE_ENV}]`);
    });
  })
  .catch((err) => {
    console.error("Falha ao conectar no MongoDB:", err.message);
    process.exit(1);
  });
