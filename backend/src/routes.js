const express = require("express");
const router = express.Router();

router.use("/jogos", require("./routes/jogos"));
router.use("/parceiros", require("./routes/parceiros"));
router.use("/ofertas", require("./routes/ofertas"));

router.get("/", (req, res) => {
  res.json({ status: "ok" });
});

module.exports = router;
