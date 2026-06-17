const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("EnergyExchange configurable split", function () {
  async function deployFixture() {
    const [owner, producer, other] = await ethers.getSigners();
    const SolarToken = await ethers.getContractFactory("SolarToken");
    const token = await SolarToken.deploy();
    await token.waitForDeployment();

    const EnergyExchange = await ethers.getContractFactory("EnergyExchange");
    const exchange = await EnergyExchange.deploy(await token.getAddress());
    await exchange.waitForDeployment();

    return { owner, producer, other, token, exchange };
  }

  it("defaults to 2000 bps reward and 8000 bps liquidity", async function () {
    const { exchange } = await deployFixture();
    expect(await exchange.BPS()).to.equal(10000n);
    expect(await exchange.rewardRatioBps()).to.equal(2000n);
  });

  it("allows owner to set reward ratio", async function () {
    const { exchange } = await deployFixture();
    await expect(exchange.setRewardRatioBps(4000))
      .to.emit(exchange, "SplitRatioUpdated")
      .withArgs(4000, 6000);
    expect(await exchange.rewardRatioBps()).to.equal(4000n);
  });

  it("rejects non-owner ratio updates", async function () {
    const { exchange, other } = await deployFixture();
    await expect(exchange.connect(other).setRewardRatioBps(4000)).to.be.reverted;
  });

  it("rejects ratios above 10000 bps", async function () {
    const { exchange } = await deployFixture();
    await expect(exchange.setRewardRatioBps(10001)).to.be.revertedWith("Invalid ratio");
  });

  it("uses configured ratio during market settlement", async function () {
    const { exchange, producer } = await deployFixture();
    await exchange.setRewardRatioBps(4000);

    await exchange.updateMarketStep(
      [producer.address],
      [200000],
      200000,
      150000
    );

    expect(await exchange.personalRewardWei(producer.address)).to.equal(ethers.parseEther("0.8"));
    expect(await exchange.globalSupplyEnergy()).to.equal(120000n);
    expect(await exchange.totalDemandEnergy()).to.equal(150000n);
  });
});
