const express = require("express");
const router = express.Router();
const Jogo = require("../models/Jogo");

// GET /jogos
router.get("/", async (req, res) => {
  const jogos = await Jogo.find().sort({ data: 1 });
  res.json(jogos);
});

// GET /jogos/:slug
router.get("/:slug", async (req, res) => {
  const jogo = await Jogo.findOne({ slug: req.params.slug });
  if (!jogo) return res.status(404).json({ erro: "Jogo não encontrado" });
  res.json(jogo);
});

module.exports = router;
