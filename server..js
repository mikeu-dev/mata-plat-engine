const express = require("express")
const axios = require("axios")
const cors = require("cors")

const app = express()
app.use(cors())

app.get("/cctv", async (req,res)=>{

    const url = "https://cctv.purwakartakab.go.id/live/cctv_pertigaan_telkom_02/index.m3u8?key=papais-cctv-pwk-2026-xK9mN3pQ&t=1773627388958"

    const response = await axios({
        method:"GET",
        url:url,
        responseType:"stream",
        headers:{
            "User-Agent":"Mozilla/5.0",
            "Referer":"https://cctv.purwakartakab.go.id/"
        }
    })

    res.setHeader("Access-Control-Allow-Origin","*")
    response.data.pipe(res)

})

app.listen(3000)