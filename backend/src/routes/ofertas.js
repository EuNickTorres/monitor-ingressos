const express = require("express");
const router = express.Router();
const Oferta = require("../models/Oferta");
const Jogo = require("../models/Jogo");
const Parceiro = require("../models/Parceiro");

// GET /ofertas
// Query params opcionais: ?jogo_slug=... | ?parceiro_slug=... | ?status=ativo|fechado
router.get("/", async (req, res) => {
  const filter = {};

  if (req.query.status) {
    filter.status = req.query.status;
  }

  if (req.query.jogo_slug) {
    const jogo = await Jogo.findOne({ slug: req.query.jogo_slug });
    if (!jogo) return res.json([]);
    filter.jogo_id = jogo._id;
  }

  if (req.query.parceiro_slug) {
    const parceiro = await Parceiro.findOne({ slug: req.query.parceiro_slug });
    if (!parceiro) return res.json([]);
    filter.parceiro_id = parceiro._id;
  }

  const ofertas = await Oferta.find(filter)
    .populate("jogo_id", "nome data slug")
    .populate("parceiro_id", "nome slug url");

  res.json(ofertas);
});

// GET /ofertas/:id
router.get("/:id", async (req, res) => {
  const oferta = await Oferta.findById(req.params.id)
    .populate("jogo_id", "nome data slug")
    .populate("parceiro_id", "nome slug url");

  if (!oferta) return res.status(404).json({ erro: "Oferta não encontrada" });
  res.json(oferta);
});

module.exports = router;
