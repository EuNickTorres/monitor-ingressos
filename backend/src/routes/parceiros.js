const express = require("express");
const router = express.Router();
const Parceiro = require("../models/Parceiro");

// GET /parceiros
router.get("/", async (req, res) => {
  const parceiros = await Parceiro.find().sort({ nome: 1 });
  res.json(parceiros);
});

// GET /parceiros/:slug
router.get("/:slug", async (req, res) => {
  const parceiro = await Parceiro.findOne({ slug: req.params.slug });
  if (!parceiro) return res.status(404).json({ erro: "Parceiro não encontrado" });
  res.json(parceiro);
});

module.exports = router;
