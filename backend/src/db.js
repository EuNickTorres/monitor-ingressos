const mongoose = require("mongoose");

async function connectDB() {
  const uri = process.env.MONGO_URI;

  await mongoose.connect(uri);

  console.log(`MongoDB conectado: ${mongoose.connection.host}`);
}

module.exports = connectDB;
