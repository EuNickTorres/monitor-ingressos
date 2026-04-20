require("dotenv").config();

const express = require("express");
const cors = require("cors");
const connectDB = require("./db");
const routes = require("./routes");

const PORT = process.env.PORT || 3000;

const app = express();

app.use(cors());
app.use(express.json());
app.use("/", routes);

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
