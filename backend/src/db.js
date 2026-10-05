const mongoose = require("mongoose");

async function connectDB() {
  const uri = process.env.MONGO_URI;

  if (!uri) {
    throw new Error("A variavel de ambiente MONGO_URI nao foi configurada");
  }

  await mongoose.connect(uri, { serverSelectionTimeoutMS: 10000 });

  console.log(`MongoDB conectado: ${mongoose.connection.host}`);
}

module.exports = connectDB;
